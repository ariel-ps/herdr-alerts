mod auto;
mod settings;
mod tui;

use rand::Rng;
use serde_json::Value;
use std::{
    env, fs,
    io::Write,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    process::{self, Command},
};

type Result<T> = std::result::Result<T, (i32, String)>;
fn failure(message: impl ToString) -> (i32, String) {
    (1, message.to_string())
}
fn usage(message: impl ToString) -> (i32, String) {
    (2, message.to_string())
}

const HELP: &str = "Herdr Alert — alerts for your coding agents.

Usage: herdr-alert COMMAND [OPTIONS]

Commands:
  tui                   Full-screen interactive configuration
  auto [blocked|done]   Ask the LLM to pick a sound fitting this project's current
                        branch/commits; cached per project+branch. Needs the claude CLI.
  auto set blocked|done NAME  Record a pick yourself, no LLM call
  auto show             Show what's cached for this project's current branch
  play [NAME]          Preview a sound with your flash and sprite settings
  list [PACK]           Browse sounds and download availability, one pack or all
  download [PACK ...]   Download sounds and available sprite artwork
  download --sprites [PACK ...]  Download only sprite artwork
  set blocked|done NAME Choose an automatic alert sound
  set blocked-sprite|done-sprite NAME  Show a different alert's sprite instead
  set blocked-sprite|done-sprite custom  Show the imported custom animation instead
  set blocked-sprite|done-sprite default  Use the sound's own paired sprite again
  set volume blocked|done NUMBER  Set that event's playback volume
  set duration NUMBER|full  Cap, or stop capping, clip playback length
  set flash on|off     Save the flash setting for previews and automatic alerts
  set sprite on|off    Save sprite visibility for previews and blocked alerts
  set animation FILE  Import a GIF/animated PNG, shown full-screen when assigned
  set animation on|off  Assign/unassign it as both blocked and done's sprite
  set animation default  Clear the imported animation entirely
  enable / disable     Enable or mute automatic alerts
  status               Check settings and audio backend

Quick start:
  herdr-alert play
  herdr-alert set flash on
  herdr-alert download mario
  herdr-alert play 1up
  herdr-alert set done 1up

Aliases: sync = download; on = enable; off = disable.
";

fn root() -> Result<PathBuf> {
    if let Some(path) = env::var_os("HERDR_PLUGIN_ROOT").filter(|v| !v.is_empty()) {
        return fs::canonicalize(path).map_err(failure);
    }
    fs::canonicalize(env::current_exe().map_err(failure)?)
        .map_err(failure)?
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .ok_or_else(|| failure("cannot locate plugin root"))
}

fn xdg(variable: &str, fallback: &str) -> Result<PathBuf> {
    env::var_os(variable)
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(fallback)))
        .ok_or_else(|| failure(format!("{variable} or HOME must be set")))
}

fn executable(name: &str) -> Option<PathBuf> {
    env::split_paths(&env::var_os("PATH").unwrap_or_default())
        .map(|dir| dir.join(name))
        .find(|path| {
            fs::metadata(path).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
        })
}

pub struct Catalog {
    data: Value,
    cache: PathBuf,
}
impl Catalog {
    pub fn load(root: &Path) -> Result<Self> {
        let data =
            serde_json::from_slice(&fs::read(root.join("data/packs.json")).map_err(failure)?)
                .map_err(failure)?;
        Ok(Self {
            data,
            cache: xdg("XDG_CACHE_HOME", ".cache")?.join("herdr-kit/sounds"),
        })
    }
    fn alert(&self, name: &str) -> Result<(&str, &str)> {
        let spec = &self.data["alerts"][name];
        let game = spec["game"]
            .as_str()
            .filter(|s| valid_name(s))
            .ok_or_else(|| failure(format!("unknown sound '{name}'. Run herdr-alert list.")))?;
        let clip = spec["clip"]
            .as_str()
            .or_else(|| {
                let mood = spec["mood"].as_str()?;
                self.data["moods"]
                    .as_object()?
                    .iter()
                    .find(|(key, _)| key.split('|').any(|s| s == mood))
                    .and_then(|(_, v)| v.as_str())
            })
            .or_else(|| self.data["sprite_sound"][spec["sprite"].as_str().unwrap_or("")].as_str())
            .unwrap_or("");
        Ok((game, clip))
    }
    /// Every alert name paired with its `vibe` tag, for `herdr-alert auto`'s
    /// prompt; alerts without one fall back to "a {game} alert" rather than
    /// being silently dropped from the model's choices.
    pub fn vibes(&self) -> Result<Vec<(String, String)>> {
        let alerts = self.data["alerts"]
            .as_object()
            .ok_or_else(|| failure("invalid alert catalog"))?;
        Ok(alerts
            .iter()
            .filter(|(name, _)| !name.starts_with('_'))
            .map(|(name, spec)| {
                let vibe = spec["vibe"]
                    .as_str()
                    .map(String::from)
                    .unwrap_or_else(|| format!("a {} alert", spec["game"].as_str().unwrap_or("?")));
                (name.clone(), vibe)
            })
            .collect())
    }
    fn alert_sprite(&self, name: &str) -> Result<(&str, &str)> {
        let spec = &self.data["alerts"][name];
        let game = spec["game"]
            .as_str()
            .filter(|s| valid_name(s))
            .ok_or_else(|| failure(format!("unknown sound '{name}'. Run herdr-alert list.")))?;
        let sprite = spec["sprite"].as_str().filter(|s| valid_name(s)).ok_or_else(|| {
            failure(format!("'{name}' has no sprite of its own. Run herdr-alert list."))
        })?;
        Ok((game, sprite))
    }
    fn resolve(&self, name: &str) -> Result<PathBuf> {
        let (game, clip) = self.alert(name)?;
        let mut files: Vec<_> = fs::read_dir(self.cache.join(game))
            .into_iter()
            .flatten()
            .filter_map(|entry| entry.ok())
            .map(|e| e.path())
            .filter(|path| {
                path.is_file()
                    && path
                        .extension()
                        .and_then(|e| e.to_str())
                        .is_some_and(|e| ["wav", "mp3", "ogg"].contains(&e))
            })
            .collect();
        files.sort();
        if let Some(file) = files
            .iter()
            .find(|path| path.file_stem().and_then(|s| s.to_str()) == Some(clip))
        {
            return Ok(file.clone());
        }
        if files.is_empty() {
            return Err(failure(format!(
                "'{name}' is not downloaded. Run herdr-alert download {game}."
            )));
        }
        Ok(files[rand::rng().random_range(0..files.len())].clone())
    }
    fn list(&self, filter: Option<&str>, config: Option<&settings::Config>) -> Result<()> {
        if let Some(game) = filter {
            let known = self.data["games"]
                .as_object()
                .ok_or_else(|| failure("invalid pack catalog"))?;
            if !known.contains_key(game) {
                return Err(usage(format!(
                    "Unknown game pack: {game}. Available: {}",
                    known.keys().filter(|n| valid_name(n)).cloned().collect::<Vec<_>>().join(", ")
                )));
            }
        }
        println!("{:<12} {:<10} {:<10} CLIP", "SOUND", "PACK", "STATUS");
        // Auto-detected: shown whenever a custom animation has been imported
        // (`set animation FILE`), regardless of filter. It's a category of
        // sprite like any other -- assigned per blocked/done event via
        // set blocked-sprite|done-sprite custom, not a separate on/off switch.
        if filter.is_none() {
            if let Some(path) = config.map(|c| c.get("HERDR_ALERT_ANIMATION")).filter(|p| !p.is_empty()) {
                let status = if Path::new(path).is_file() { "ready" } else { "missing" };
                let config = config.unwrap();
                let assigned: Vec<&str> = [("blocked", "HERDR_SPRITE_BLOCKED"), ("done", "HERDR_SPRITE_DONE")]
                    .iter()
                    .filter(|(_, key)| config.get(key) == "custom")
                    .map(|(event, _)| *event)
                    .collect();
                let clip = if assigned.is_empty() {
                    "not assigned; set blocked-sprite|done-sprite custom".to_string()
                } else {
                    format!("assigned: {}", assigned.join("+"))
                };
                println!("{:<12} {:<10} {:<10} {}", "(custom)", "custom", status, clip);
            }
        }
        let alerts = self.data["alerts"]
            .as_object()
            .ok_or_else(|| failure("invalid alert catalog"))?;
        let mut shown = 0;
        for name in alerts.keys().filter(|name| !name.starts_with('_')) {
            let (game, clip) = self.alert(name)?;
            if filter.is_some_and(|f| f != game) {
                continue;
            }
            shown += 1;
            let status = if self.resolve(name).is_ok() {
                "ready"
            } else {
                "missing"
            };
            println!(
                "{name:<12} {game:<10} {status:<10} {}",
                if clip.is_empty() { "(any)" } else { clip }
            );
        }
        if shown == 0 {
            println!("(no alerts for this pack)");
        }
        println!("\nPreview:  herdr-alert play NAME\nDownload: herdr-alert download PACK");
        Ok(())
    }
    fn download(&self, root: &Path, requested: &[String], sprites_only: bool) -> Result<()> {
        let packs = self.data["games"]
            .as_object()
            .ok_or_else(|| failure("invalid pack catalog"))?;
        let available: Vec<_> = packs
            .iter()
            .filter(|(name, spec)| {
                valid_name(name)
                    && spec["sounds"].is_string()
                    && (!sprites_only || spec["sprites"].is_string())
            })
            .map(|(name, _)| name.clone())
            .collect();
        let games = if requested.is_empty() {
            &available
        } else {
            requested
        };
        for game in games {
            if !available.contains(game) {
                return Err(usage(format!(
                    "Unknown game pack: {game}. Available: {}",
                    available.join(", ")
                )));
            }
        }
        let uv =
            executable("uv").ok_or_else(|| failure("uv is required to download alert packs"))?;
        let mut failed = false;
        for game in games {
            eprintln!("\nDownloading {game}...");
            if !sprites_only {
                let mut command = Command::new(&uv);
                command.args(["run", "--no-project"]);
                if game == "redalert" {
                    command
                        .args(["--with", "pycryptodome", "python"])
                        .arg(root.join("libexec/fetch-redalert-sounds.py"));
                } else {
                    let source = packs[game]["sounds"].as_str().unwrap();
                    let identifier = source
                        .strip_prefix("archive:")
                        .ok_or_else(|| failure(format!("unsupported source: {source}")))?;
                    command
                        .arg("python")
                        .arg(root.join("libexec/fetch-game-sounds.py"))
                        .arg(identifier);
                }
                if !command
                    .arg(self.cache.join(game))
                    .status()
                    .map_err(failure)?
                    .success()
                {
                    failed = true;
                }
            }
            if packs[game]["sprites"].is_string() {
                let directory = self.cache.parent().unwrap().join("sprites");
                let mut command = Command::new(&uv);
                command.args(["run", "--no-project", "--with", "pillow"]);
                if game == "redalert" {
                    command
                        .args(["--with", "pycryptodome", "python"])
                        .arg(root.join("libexec/fetch-redalert-sprites.py"))
                        .arg(directory.join(game));
                } else {
                    command
                        .arg("python")
                        .arg(root.join("libexec/fetch-sprites.py"))
                        .arg(&directory)
                        .arg(game);
                }
                if !command.status().map_err(failure)?.success() {
                    failed = true;
                }
            }
        }
        if failed {
            Err(failure(
                "one or more sound or sprite packs failed to download",
            ))
        } else {
            Ok(())
        }
    }
}

fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && !name.starts_with(['-', '_'])
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

fn play_file(path: &Path, volume: &str, duration: &str) -> Result<()> {
    fs::File::open(path)
        .map_err(|e| failure(format!("cannot read sound file {}: {e}", path.display())))?;
    let volume_number = volume
        .parse::<f64>()
        .ok()
        .filter(|v| v.is_finite() && *v >= 0.0)
        .ok_or_else(|| failure("volume must be a finite nonnegative number"))?;
    if !duration.is_empty()
        && duration
            .parse::<f64>()
            .ok()
            .filter(|v| v.is_finite() && *v > 0.0)
            .is_none()
    {
        return Err(failure("duration must be a finite positive number"));
    }
    if let Some(player) = executable("afplay") {
        let mut command = Command::new(player);
        command.args(["-v", &volume_number.to_string()]);
        if !duration.is_empty() {
            command.args(["-t", duration]);
        }
        let status = command.arg(path).status().map_err(failure)?;
        if !status.success() {
            return Err((
                status.code().unwrap_or(1),
                "playback failed. Check your audio output.".into(),
            ));
        }
    } else if let Some(player) = executable("ffplay") {
        let mut command = Command::new(player);
        command.args([
            "-nodisp",
            "-autoexit",
            "-nostats",
            "-loglevel",
            "error",
            "-af",
            &format!("volume={volume_number}"),
        ]);
        if !duration.is_empty() {
            command.args(["-t", duration]);
        }
        let output = command.arg("-i").arg(path).output().map_err(failure)?;
        if !output.status.success() || !output.stderr.is_empty() {
            let _ = std::io::stderr().write_all(&output.stderr);
            return Err((
                output.status.code().filter(|c| *c != 0).unwrap_or(1),
                "playback failed. Check your audio output and that other apps can play sound."
                    .into(),
            ));
        }
    } else {
        return Err(failure("no audio player found. Install FFmpeg on Linux."));
    }
    Ok(())
}

fn preview(root: &Path, name: Option<&str>, flash_flag: bool, custom_scene: bool) -> Result<()> {
    let config = settings::Config::load(root)?;
    let flash = flash_flag || config.flash_enabled();
    let sprite = matches!(config.get("HERDR_ALERT_SPRITE"), "" | "1");
    let pane = env::var("HERDR_PANE_ID").unwrap_or_default();
    if (flash || sprite)
        && !pane
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b':'))
    {
        return Err(failure(
            "invalid HERDR_PANE_ID; unset it when running outside Herdr.",
        ));
    }
    let path = if let Some(name) = name {
        Catalog::load(root)?.resolve(name)?
    } else {
        root.join("assets/audio/8bit-alert.wav")
    };
    println!("Playing {}...", name.unwrap_or("included tone"));
    let volume = config.get("HERDR_VOLUME_DONE");
    let mut visual = if flash || sprite {
        let mut command = Command::new("zsh");
        command
            .arg(root.join("libexec/herdr-visuals"))
            .arg(&pane)
            .arg("preview")
            .arg(name.unwrap_or(""))
            .arg(if flash { "1" } else { "0" })
            .arg(if sprite { "1" } else { "0" });
        // Always set explicitly, never left to the ambient environment: an
        // explicit request to preview the imported scene itself (the tui's
        // "(custom animation)" row) forces it on; anything else must not
        // inherit a stray SPRITE_FILE from whatever spawned this process.
        if custom_scene {
            command
                .env("SPRITE_FILE", config.get("HERDR_ALERT_ANIMATION"))
                .env("SPRITE_FULLSCREEN", "1");
        } else {
            command.env("SPRITE_FILE", "").env("SPRITE_FULLSCREEN", "");
        }
        Some(command.spawn().map_err(failure)?)
    } else {
        None
    };
    let audio = play_file(
        &path,
        if volume.is_empty() { "1.0" } else { volume },
        config.get("HERDR_ALERT_MAX_SECONDS"),
    );
    let visual = visual
        .as_mut()
        .map(|child| child.wait())
        .transpose()
        .map_err(failure)?;
    audio?;
    if visual.is_some_and(|status| !status.success()) {
        return Err(failure("visual effects did not complete"));
    }
    Ok(())
}

fn status(root: &Path, catalog: &Catalog, config: &settings::Config) -> Result<()> {
    let project = env::current_dir().ok().and_then(|cwd| auto::lookup(&cwd));
    println!(
        "Herdr Alert\n\n  {:<18} {}",
        "Automatic alerts",
        if config.get("HERDR_ALERT_OFF") == "1" {
            "disabled"
        } else {
            "enabled (requires the plugin to be enabled)"
        }
    );
    if let Some(p) = &project {
        println!("  {:<18} {} (branch {})", "Project", p.repo_root, p.branch);
    }
    println!(
        "  {:<18} {}",
        "Flash",
        if config.flash_enabled() { "on" } else { "off" }
    );
    let duration = config.get("HERDR_ALERT_MAX_SECONDS");
    let animation = config.get("HERDR_ALERT_ANIMATION");
    if !animation.is_empty() {
        println!(
            "  {:<18} {}{}",
            "Animation file",
            animation,
            if Path::new(animation).is_file() {
                ""
            } else {
                " (missing; using fallback)"
            }
        );
        println!("  {:<18} assign with set blocked-sprite|done-sprite custom (see below)", "");
    }
    println!(
        "  {:<18} {} (previews and blocked-agent alerts)",
        "Sprite",
        if matches!(config.get("HERDR_ALERT_SPRITE"), "" | "1") {
            "on"
        } else {
            "off"
        }
    );
    println!(
        "  {:<18} {}\n\nAlerts\n  {:<10} {:<8} SOUND",
        "Duration limit",
        if duration.is_empty() {
            "no limit".into()
        } else {
            format!("{duration} seconds")
        },
        "EVENT",
        "VOLUME"
    );
    for event in ["blocked", "done"] {
        let upper = event.to_uppercase();
        let mut name = config.get(&format!("HERDR_ALERT_{upper}")).to_string();
        if name.is_empty() {
            name = catalog.data["states"][event]
                .as_str()
                .unwrap_or("")
                .to_string();
        }
        let custom = config.get(&format!("HERDR_SOUND_{upper}"));
        let availability = if !custom.is_empty() && fs::File::open(custom).is_ok() {
            name = custom.into();
            "custom file"
        } else if catalog.resolve(&name).is_ok() {
            "ready"
        } else {
            "unavailable; using bundled tone"
        };
        let volume = config.get(&format!("HERDR_VOLUME_{upper}"));
        let volume = if volume.is_empty() {
            if event == "blocked" {
                "1.8"
            } else {
                "1.0"
            }
        } else {
            volume
        };
        println!("  {event:<10} {volume:<8} {name} ({availability})");
        let sprite_override = config.get(&format!("HERDR_SPRITE_{upper}"));
        if sprite_override == "custom" {
            println!("             sprite override: custom animation");
        } else if !sprite_override.is_empty() {
            println!("             sprite override: {sprite_override}");
        }
        let project_pick = project.as_ref().and_then(|p| {
            if event == "blocked" { p.blocked.as_ref() } else { p.done.as_ref() }
        });
        if let Some(pick) = project_pick {
            println!("             project override: {pick} (wins over the plain name above)");
        }
    }
    let player = executable("afplay")
        .or_else(|| executable("ffplay"))
        .ok_or_else(|| failure("no audio player found. Install FFmpeg on Linux."))?;
    println!(
        "\nAudio\n  {:<18} {}\n  {:<18} {}\n\nTest speakers: herdr-alert play",
        "Player",
        player.display(),
        "Configuration",
        settings::config_file(root)?.display()
    );
    Ok(())
}

fn execute(mut args: Vec<String>) -> Result<()> {
    if args.first().is_some_and(|arg| arg == "--alert8play") {
        args.remove(0);
        match args.first().map(String::as_str) {
            Some("--list") if args.len() == 1 => args = vec!["list".into()],
            Some("--help" | "-h") if args.len() == 1 => {
                println!("usage: alert8play [NAME]\n       alert8play --list | --help\nCompatibility command for herdr-alert play.\nSettings: herdr-alert set flash|sprite|animation on|off");
                return Ok(());
            }
            _ => args.insert(0, "play".into()),
        }
    }
    if args.is_empty()
        || matches!(args[0].as_str(), "-h" | "--help")
        || (args.len() == 2 && args[1] == "--help")
    {
        print!("{HELP}");
        return Ok(());
    }
    if args[0] == "play-file" {
        if !(2..=4).contains(&args.len()) {
            return Err(usage("play-file requires PATH [VOLUME [DURATION]]"));
        }
        return play_file(
            Path::new(&args[1]),
            args.get(2).map(String::as_str).unwrap_or("1.0"),
            args.get(3).map(String::as_str).unwrap_or(""),
        );
    }
    let root = root()?;
    let command = match args[0].as_str() {
        "sync" => "download",
        "on" => "enable",
        "off" => "disable",
        other => other,
    };
    match command {
        "play" => {
            let mut flash = false;
            let mut name = None;
            for arg in &args[1..] {
                if arg == "--flash" && !flash {
                    flash = true;
                } else if !arg.starts_with('-') && name.is_none() {
                    name = Some(arg.as_str());
                } else {
                    return Err(usage("usage: herdr-alert play [NAME] [--flash]"));
                }
            }
            preview(&root, name, flash, false)
        }
        "tui" if args.len() == 1 => tui::run(&root),
        "auto" if args.len() == 4 && args[1] == "set" => auto::set(&root, &args[2], &args[3]),
        "auto" if args.len() == 2 && args[1] == "show" => auto::show(&root),
        "auto" if args.len() <= 2 => auto::run(&root, args.get(1).map(String::as_str)),
        "list" if args.len() <= 2 => Catalog::load(&root)?
            .list(args.get(1).map(String::as_str), settings::Config::load(&root).ok().as_ref()),
        "status" if args.len() == 1 => status(
            &root,
            &Catalog::load(&root)?,
            &settings::Config::load(&root)?,
        ),
        "download" => {
            let sprites_only = args.get(1).is_some_and(|arg| arg == "--sprites");
            Catalog::load(&root)?.download(
                &root,
                &args[if sprites_only { 2 } else { 1 }..],
                sprites_only,
            )
        }
        "enable" | "disable" if args.len() == 1 => {
            settings::save(
                &root,
                &[(
                    "HERDR_ALERT_OFF".into(),
                    if command == "disable" {
                        "1".into()
                    } else {
                        "0".into()
                    },
                )],
            )?;
            println!(
                "Automatic alerts {}",
                if command == "enable" {
                    "enabled."
                } else {
                    "disabled. Manual previews still work."
                }
            );
            Ok(())
        }
        "set"
            if args.len() == 3
                && args[1] == "animation"
                && !["on", "off"].contains(&args[2].as_str()) =>
        {
            let animation = if args[2] == "default" {
                String::new()
            } else {
                let source = fs::canonicalize(&args[2]).map_err(failure)?;
                let uv = executable("uv")
                    .ok_or_else(|| failure("uv is required to import animations"))?;
                let output = Command::new(uv)
                    .args(["run", "--no-project", "--with", "pillow", "python"])
                    .arg(root.join("libexec/import-animation.py"))
                    .arg(source)
                    .arg(xdg("XDG_DATA_HOME", ".local/share")?.join("herdr-alert/animations"))
                    .stderr(process::Stdio::inherit())
                    .output()
                    .map_err(failure)?;
                if !output.status.success() {
                    return Err(failure("animation import failed; settings unchanged"));
                }
                let path = String::from_utf8(output.stdout)
                    .map_err(failure)?
                    .trim()
                    .to_owned();
                if path.is_empty() || !Path::new(&path).is_file() {
                    return Err(failure("animation importer did not produce a file"));
                }
                path
            };
            settings::save(&root, &[("HERDR_ALERT_ANIMATION".into(), animation)])?;
            println!("Animation updated. Preview: herdr-alert play\nAssign it with: herdr-alert set animation on\nSprites must be enabled: herdr-alert set sprite on");
            Ok(())
        }
        // Convenience alias over the real mechanism: the custom animation is a
        // category of sprite like any other (see set blocked-sprite/done-sprite
        // custom below), not a separate master switch. This just assigns or
        // clears "custom" on both events at once instead of one at a time.
        "set" if args.len() == 3 && args[1] == "animation" && ["on", "off"].contains(&args[2].as_str()) =>
        {
            if args[2] == "on" {
                let animation = settings::Config::load(&root)?.get("HERDR_ALERT_ANIMATION").to_string();
                if animation.is_empty() {
                    return Err(usage(
                        "No animation imported yet. Run herdr-alert set animation FILE first.",
                    ));
                }
                settings::save(
                    &root,
                    &[
                        ("HERDR_SPRITE_BLOCKED".into(), "custom".into()),
                        ("HERDR_SPRITE_DONE".into(), "custom".into()),
                    ],
                )?;
                println!("Custom animation assigned as blocked and done's sprite.");
            } else {
                // Only clear slots actually pointing at it, so this never
                // clobbers an unrelated blocked-sprite/done-sprite choice.
                let config = settings::Config::load(&root)?;
                let mut updates = Vec::new();
                if config.get("HERDR_SPRITE_BLOCKED") == "custom" {
                    updates.push(("HERDR_SPRITE_BLOCKED".into(), String::new()));
                }
                if config.get("HERDR_SPRITE_DONE") == "custom" {
                    updates.push(("HERDR_SPRITE_DONE".into(), String::new()));
                }
                settings::save(&root, &updates)?;
                println!("Custom animation unassigned; sprites revert to each sound's own.");
            }
            Ok(())
        }
        "set" if args.len() == 3 && ["flash", "sprite"].contains(&args[1].as_str()) => {
            let value = match args[2].as_str() {
                "on" => "1",
                "off" => "0",
                _ => return Err(usage(format!("usage: herdr-alert set {} on|off", args[1]))),
            };
            settings::save(
                &root,
                &[(format!("HERDR_ALERT_{}", args[1].to_uppercase()), value.into())],
            )?;
            if args[1] == "sprite" {
                println!("Sprite {} (previews and blocked-agent alerts).", args[2]);
            } else {
                println!("Flash {} (previews and automatic alerts).", args[2]);
            }
            Ok(())
        }
        "set" if args.len() == 3 && ["blocked", "done"].contains(&args[1].as_str()) => {
            if !valid_name(&args[2]) || Catalog::load(&root)?.alert(&args[2]).is_err() {
                return Err(usage(format!(
                    "Unknown sound: {}. Run herdr-alert list.",
                    args[2]
                )));
            }
            let event = args[1].to_uppercase();
            settings::save(
                &root,
                &[
                    (format!("HERDR_ALERT_{event}"), args[2].clone()),
                    (format!("HERDR_SOUND_{event}"), String::new()),
                ],
            )?;
            println!(
                "Updated {} sound to {}.\nPreview: herdr-alert play {}",
                args[1], args[2], args[2]
            );
            Ok(())
        }
        "set"
            if args.len() == 3 && ["blocked-sprite", "done-sprite"].contains(&args[1].as_str()) =>
        {
            let event = args[1].trim_end_matches("-sprite").to_uppercase();
            let value = if args[2] == "default" {
                String::new()
            } else if args[2] == "custom" {
                let animation = settings::Config::load(&root)?.get("HERDR_ALERT_ANIMATION").to_string();
                if animation.is_empty() {
                    return Err(usage(
                        "No animation imported yet. Run herdr-alert set animation FILE first.",
                    ));
                }
                "custom".to_string()
            } else {
                let catalog = Catalog::load(&root)?;
                let (game, sprite) = catalog.alert_sprite(&args[2])?;
                format!("{game}:{sprite}")
            };
            settings::save(&root, &[(format!("HERDR_SPRITE_{event}"), value)])?;
            if args[2] == "custom" {
                println!(
                    "{} now shows the imported custom animation.\nPreview: herdr-alert play",
                    args[1]
                );
            } else {
                println!(
                    "{} now shows {}'s sprite.\nPreview the paired sound separately: herdr-alert play {}",
                    args[1], args[2], args[2]
                );
            }
            Ok(())
        }
        "set" if args.len() == 4 && args[1] == "volume" && ["blocked", "done"].contains(&args[2].as_str()) =>
        {
            let volume = args[3]
                .parse::<f64>()
                .ok()
                .filter(|v| v.is_finite() && *v >= 0.0)
                .ok_or_else(|| usage("volume must be a finite nonnegative number"))?;
            settings::save(
                &root,
                &[(format!("HERDR_VOLUME_{}", args[2].to_uppercase()), volume.to_string())],
            )?;
            println!("Updated {} volume to {volume}.", args[2]);
            Ok(())
        }
        "set" if args.len() == 3 && args[1] == "duration" => {
            let value = if args[2] == "full" {
                String::new()
            } else {
                let seconds = args[2]
                    .parse::<f64>()
                    .ok()
                    .filter(|v| v.is_finite() && *v > 0.0)
                    .ok_or_else(|| usage("duration must be a finite positive number, or full"))?;
                seconds.to_string()
            };
            settings::save(&root, &[("HERDR_ALERT_MAX_SECONDS".into(), value)])?;
            println!(
                "Duration {}.",
                if args[2] == "full" { "uncapped".into() } else { format!("capped at {} seconds", args[2]) }
            );
            Ok(())
        }
        _ => Err(usage(
            "unknown command or invalid arguments. Run herdr-alert --help.",
        )),
    }
}

fn main() {
    if let Err((code, message)) = execute(env::args().skip(1).collect()) {
        eprintln!("herdr-alert: {message}");
        process::exit(code);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn catalog_preserves_mood_and_sprite_clip_mappings() {
        let catalog = Catalog {
            data: serde_json::from_str(include_str!("../data/packs.json")).unwrap(),
            cache: PathBuf::new(),
        };
        assert_eq!(catalog.alert("tesla").unwrap(), ("redalert", "TSLACHG2"));
        assert_eq!(catalog.alert("1up").unwrap(), ("mario", "1up"));
        assert_eq!(catalog.alert("coin").unwrap(), ("mario", "coin (nes)"));
        assert!(catalog.alert("_comment").is_err());
        assert!(catalog.alert("../escape").is_err());
    }
}

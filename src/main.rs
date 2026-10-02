mod settings;

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

const HELP: &str = "Herdr Sound — alerts for your coding agents.

Usage: herdr-sound COMMAND [OPTIONS]

Commands:
  play [NAME]          Preview a sound using your flash setting
  list                  Browse sounds and download availability
  download [PACK ...]   Download selected packs, or all sound packs
  set blocked|done NAME Choose an automatic alert sound
  set flash on|off     Save the flash setting for previews and automatic alerts
  enable / disable     Enable or mute automatic alerts
  status               Check settings and audio backend

Quick start:
  herdr-sound play
  herdr-sound set flash on
  herdr-sound download mario
  herdr-sound play 1up
  herdr-sound set done 1up

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

struct Catalog {
    data: Value,
    cache: PathBuf,
}
impl Catalog {
    fn load(root: &Path) -> Result<Self> {
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
            .ok_or_else(|| failure(format!("unknown sound '{name}'. Run herdr-sound list.")))?;
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
                "'{name}' is not downloaded. Run herdr-sound download {game}."
            )));
        }
        Ok(files[rand::rng().random_range(0..files.len())].clone())
    }
    fn list(&self) -> Result<()> {
        println!("{:<12} {:<10} {:<10} CLIP", "SOUND", "PACK", "STATUS");
        let alerts = self.data["alerts"]
            .as_object()
            .ok_or_else(|| failure("invalid alert catalog"))?;
        for name in alerts.keys().filter(|name| !name.starts_with('_')) {
            let (game, clip) = self.alert(name)?;
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
        println!("\nPreview:  herdr-sound play NAME\nDownload: herdr-sound download PACK");
        Ok(())
    }
    fn download(&self, root: &Path, requested: &[String]) -> Result<()> {
        let packs = self.data["games"]
            .as_object()
            .ok_or_else(|| failure("invalid pack catalog"))?;
        let available: Vec<_> = packs
            .iter()
            .filter(|(name, spec)| valid_name(name) && spec["sounds"].is_string())
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
            executable("uv").ok_or_else(|| failure("uv is required to download sound packs"))?;
        let mut failed = false;
        for game in games {
            eprintln!("\nDownloading {game}...");
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
        if failed {
            Err(failure("one or more sound packs failed to download"))
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

fn status(root: &Path, catalog: &Catalog, config: &settings::Config) -> Result<()> {
    println!(
        "Herdr Sound\n\n  {:<18} {}",
        "Automatic alerts",
        if config.get("HERDR_ALERT_OFF") == "1" {
            "disabled"
        } else {
            "enabled (requires the plugin to be enabled)"
        }
    );
    println!(
        "  {:<18} {}",
        "Flash",
        if config.flash_enabled() { "on" } else { "off" }
    );
    let duration = config.get("HERDR_ALERT_MAX_SECONDS");
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
    }
    let player = executable("afplay")
        .or_else(|| executable("ffplay"))
        .ok_or_else(|| failure("no audio player found. Install FFmpeg on Linux."))?;
    println!(
        "\nAudio\n  {:<18} {}\n  {:<18} {}\n\nTest speakers: herdr-sound play",
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
                println!("usage: alert8play [NAME]\n       alert8play --list | --help\nCompatibility command for herdr-sound play.\nFlash setting: herdr-sound set flash on|off");
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
                    return Err(usage("usage: herdr-sound play [NAME] [--flash]"));
                }
            }
            let config = settings::Config::load(&root)?;
            flash |= config.flash_enabled();
            let pane = env::var("HERDR_PANE_ID").unwrap_or_default();
            if flash
                && !pane
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b':'))
            {
                return Err(failure(
                    "invalid HERDR_PANE_ID; unset it when running outside Herdr.",
                ));
            }
            let path = if let Some(name) = name {
                Catalog::load(&root)?.resolve(name)?
            } else {
                root.join("assets/audio/8bit-alert.wav")
            };
            println!("Playing {}...", name.unwrap_or("included tone"));
            let volume = config.get("HERDR_VOLUME_DONE");
            let mut visual = if flash {
                Some(
                    Command::new("zsh")
                        .arg(root.join("libexec/herdr-flash"))
                        .arg(&pane)
                        .spawn()
                        .map_err(failure)?,
                )
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
                return Err(failure("flash did not complete"));
            }
            Ok(())
        }
        "list" if args.len() == 1 => Catalog::load(&root)?.list(),
        "status" if args.len() == 1 => status(
            &root,
            &Catalog::load(&root)?,
            &settings::Config::load(&root)?,
        ),
        "download" => Catalog::load(&root)?.download(&root, &args[1..]),
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
        "set" if args.len() == 3 && args[1] == "flash" => {
            let value = match args[2].as_str() {
                "on" => "1",
                "off" => "0",
                _ => return Err(usage("usage: herdr-sound set flash on|off")),
            };
            settings::save(&root, &[("HERDR_ALERT_FLASH".into(), value.into())])?;
            println!("Flash {} (previews and automatic alerts).", args[2]);
            Ok(())
        }
        "set" if args.len() == 3 && ["blocked", "done"].contains(&args[1].as_str()) => {
            if !valid_name(&args[2]) || Catalog::load(&root)?.alert(&args[2]).is_err() {
                return Err(usage(format!(
                    "Unknown sound: {}. Run herdr-sound list.",
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
                "Updated {} sound to {}.\nPreview: herdr-sound play {}",
                args[1], args[2], args[2]
            );
            Ok(())
        }
        _ => Err(usage(
            "unknown command or invalid arguments. Run herdr-sound --help.",
        )),
    }
}

fn main() {
    if let Err((code, message)) = execute(env::args().skip(1).collect()) {
        eprintln!("herdr-sound: {message}");
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

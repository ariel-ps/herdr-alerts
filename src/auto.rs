// `herdr-alert auto [blocked|done]`: ask an LLM to pick a project-fitting
// alert from the current git branch name and recent commit subjects, cached
// per repository so the per-pane hook can apply it without a network call.
//
// Deliberately on-demand and explicit, not automatic: this shells out to the
// `claude` CLI, which costs money and ~10-15s per call, so it only ever runs
// when the user asks for it, never from the latency-sensitive status hook.
use crate::{executable, failure, usage, valid_name, Catalog, Result};
use serde_json::{json, Value};
use std::{
    env, fs,
    os::unix::fs::OpenOptionsExt,
    path::{Path, PathBuf},
    process::Command,
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Clone, Copy)]
pub enum Scope {
    Both,
    Blocked,
    Done,
}
impl Scope {
    fn parse(arg: Option<&str>) -> Result<Self> {
        match arg {
            None => Ok(Scope::Both),
            Some("blocked") => Ok(Scope::Blocked),
            Some("done") => Ok(Scope::Done),
            _ => Err(usage("usage: herdr-alert auto [blocked|done]")),
        }
    }
    fn wants(self, event: &str) -> bool {
        matches!((self, event), (Scope::Both, _) | (Scope::Blocked, "blocked") | (Scope::Done, "done"))
    }
}

fn git(dir: &Path, args: &[&str]) -> Option<String> {
    let output = Command::new("git").args(args).current_dir(dir).output().ok()?;
    output
        .status
        .success()
        .then(|| String::from_utf8_lossy(&output.stdout).trim().to_owned())
        .filter(|s| !s.is_empty())
}

fn projects_file() -> Result<PathBuf> {
    Ok(crate::xdg("XDG_DATA_HOME", ".local/share")?.join("herdr-alert/projects.json"))
}

fn load_projects() -> Result<Value> {
    let path = projects_file()?;
    match fs::read(&path) {
        Ok(bytes) => serde_json::from_slice(&bytes).map_err(failure),
        Err(_) => Ok(json!({})),
    }
}

fn save_projects(data: &Value) -> Result<()> {
    let path = projects_file()?;
    let parent = path.parent().ok_or_else(|| failure("invalid cache path"))?;
    fs::create_dir_all(parent).map_err(failure)?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(failure)?
        .as_nanos();
    let temporary = parent.join(format!(".projects.json.{}.{stamp}", std::process::id()));
    let result = (|| -> std::io::Result<()> {
        let mut file = fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&temporary)?;
        serde_json::to_writer_pretty(&mut file, data)?;
        use std::io::Write;
        file.write_all(b"\n")?;
        file.sync_all()?;
        fs::rename(&temporary, &path)
    })();
    let _ = fs::remove_file(&temporary);
    result.map_err(failure)
}

pub fn run(root: &Path, arg: Option<&str>) -> Result<()> {
    let scope = Scope::parse(arg)?;
    let cwd = env::current_dir().map_err(failure)?;
    let repo_root = git(&cwd, &["rev-parse", "--show-toplevel"]).ok_or_else(|| {
        usage("Run herdr-alert auto from inside a git project; none was found here.")
    })?;
    let branch = git(&cwd, &["rev-parse", "--abbrev-ref", "HEAD"]).unwrap_or_else(|| "(unknown)".into());
    let commits = git(&cwd, &["log", "-5", "--pretty=%s"]).unwrap_or_default();

    let catalog = Catalog::load(root)?;
    let mut vibes = catalog.vibes()?;
    vibes.sort();
    let names: Vec<&str> = vibes.iter().map(|(n, _)| n.as_str()).collect();
    let catalog_block = vibes
        .iter()
        .map(|(name, vibe)| format!("- {name}: {vibe}"))
        .collect::<Vec<_>>()
        .join("\n");

    let claude = executable("claude").ok_or_else(|| {
        failure("the `claude` CLI is required for herdr-alert auto. Install Claude Code, or set sounds manually with herdr-alert set blocked|done.")
    })?;
    let schema = json!({
        "type": "object",
        "properties": {
            "blocked": {"type": "string", "enum": names},
            "done": {"type": "string", "enum": names},
        },
        "required": ["blocked", "done"],
        "additionalProperties": false,
    });
    let system_prompt = "You pick retro-game-themed alert sounds that fit a software project's current \
        work, from a fixed catalog. 'blocked' fires when a coding agent hits a snag and needs a human; \
        'done' fires when it finishes successfully. Pick the single best-fitting catalog entry for each, \
        based only on the vibe tags given -- do not invent reasoning beyond matching tone. Respond only \
        through the required JSON schema.";
    let user_prompt = format!(
        "Git branch: {branch}\nRecent commits:\n{}\n\nCatalog:\n{catalog_block}",
        if commits.is_empty() { "(none yet)".into() } else { commits }
    );

    let output = Command::new(&claude)
        .args(["-p", "--safe-mode", "--model", "haiku", "--tools", ""])
        .args(["--output-format", "json", "--max-budget-usd", "0.05"])
        .arg("--system-prompt")
        .arg(system_prompt)
        .arg("--json-schema")
        .arg(schema.to_string())
        .arg(&user_prompt)
        .output()
        .map_err(failure)?;
    if !output.status.success() {
        return Err(failure(format!(
            "claude CLI failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        )));
    }
    let response: Value = serde_json::from_slice(&output.stdout).map_err(failure)?;
    if response["is_error"].as_bool() == Some(true) {
        let message = response["errors"]
            .as_array()
            .and_then(|e| e.first())
            .and_then(|e| e.as_str())
            .unwrap_or("unknown error");
        return Err(failure(format!("claude CLI returned an error: {message}")));
    }
    let picked = &response["structured_output"];
    let pick = |event: &str| -> Result<String> {
        let name = picked[event]
            .as_str()
            .ok_or_else(|| failure("claude did not return a usable pick"))?;
        if !valid_name(name) || !names.contains(&name) {
            return Err(failure(format!("claude picked an unknown alert: {name}")));
        }
        Ok(name.to_owned())
    };
    let blocked = pick("blocked")?;
    let done = pick("done")?;

    let mut projects = load_projects()?;
    let entry = projects
        .as_object_mut()
        .ok_or_else(|| failure("invalid project cache"))?
        .entry(repo_root.clone())
        .or_insert_with(|| json!({}));
    if scope.wants("blocked") {
        entry["blocked"] = json!(blocked);
    }
    if scope.wants("done") {
        entry["done"] = json!(done);
    }
    save_projects(&projects)?;

    println!("Branch: {branch}\n");
    for (event, name) in [("blocked", &blocked), ("done", &done)] {
        let saved = if scope.wants(event) {
            "saved".to_owned()
        } else {
            format!("not saved; herdr-alert auto {event} to save it")
        };
        println!("  {event:<8} {name:<12} ({saved})");
    }
    println!("\nApplies only inside {repo_root}\nPreview: herdr-alert play {blocked}");
    Ok(())
}

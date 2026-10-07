// `herdr-alert auto`: pick a project-fitting alert from the current git
// branch name and recent commit subjects, cached per project+branch so the
// per-pane hook can apply it without a network call.
//
// Deliberately on-demand and explicit, not automatic: classification is never
// invoked from the latency-sensitive status hook, only when a human (or an
// orchestrating agent) asks for it.
//
// Two ways to classify:
//   herdr-alert auto [blocked|done]            spawn the `claude` CLI itself
//   herdr-alert auto set blocked|done NAME     record a pick an agent already
//                                              made in its own reasoning, with
//                                              no subprocess spent re-asking
//
// Cached by PROJECT (the repository's git-common-dir, identical across every
// worktree of that repository) and then by BRANCH within it (or, for a
// detached-HEAD worktree with no branch name, by that worktree's own
// toplevel path) -- so switching branches in one checkout, or working in a
// second worktree of the same project, each resolve their own pick instead
// of silently reusing whatever was last computed for that directory.
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
enum Events {
    Both,
    Blocked,
    Done,
}
impl Events {
    fn parse(arg: Option<&str>) -> Result<Self> {
        match arg {
            None => Ok(Events::Both),
            Some("blocked") => Ok(Events::Blocked),
            Some("done") => Ok(Events::Done),
            _ => Err(usage("usage: herdr-alert auto [blocked|done]")),
        }
    }
    fn wants(self, event: &str) -> bool {
        matches!((self, event), (Events::Both, _) | (Events::Blocked, "blocked") | (Events::Done, "done"))
    }
}

struct Scope {
    /// The repository's git-common-dir, absolute -- identical across every
    /// worktree of the same clone, so it identifies the PROJECT rather than
    /// any one checkout of it.
    project_key: String,
    /// The branch name, or "detached:<toplevel>" for a worktree with no
    /// branch (a detached HEAD) -- distinguishes branches, and distinguishes
    /// detached worktrees from each other since they'd otherwise all report
    /// branch "HEAD".
    scope_key: String,
    /// This checkout's own directory, for human-facing messages only.
    repo_root: String,
    /// The raw branch name ("HEAD" if detached), for human-facing messages.
    branch: String,
}

fn git(dir: &Path, args: &[&str]) -> Option<String> {
    let output = Command::new("git").args(args).current_dir(dir).output().ok()?;
    output
        .status
        .success()
        .then(|| String::from_utf8_lossy(&output.stdout).trim().to_owned())
        .filter(|s| !s.is_empty())
}

fn resolve_scope(cwd: &Path) -> Result<Scope> {
    let repo_root = git(cwd, &["rev-parse", "--show-toplevel"]).ok_or_else(|| {
        usage("Run herdr-alert auto from inside a git project; none was found here.")
    })?;
    let project_key = git(cwd, &["rev-parse", "--path-format=absolute", "--git-common-dir"])
        .ok_or_else(|| failure("could not resolve this repository's git directory"))?;
    let branch = git(cwd, &["rev-parse", "--abbrev-ref", "HEAD"]).unwrap_or_else(|| "HEAD".into());
    let scope_key = if branch == "HEAD" { format!("detached:{repo_root}") } else { branch.clone() };
    Ok(Scope { project_key, scope_key, repo_root, branch })
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

fn apply_pick(scope: &Scope, updates: &[(&str, &str)]) -> Result<()> {
    let mut projects = load_projects()?;
    let project = projects
        .as_object_mut()
        .ok_or_else(|| failure("invalid project cache"))?
        .entry(scope.project_key.clone())
        .or_insert_with(|| json!({}));
    let entry = project
        .as_object_mut()
        .ok_or_else(|| failure("invalid project cache"))?
        .entry(scope.scope_key.clone())
        .or_insert_with(|| json!({}));
    for (event, name) in updates {
        entry[*event] = json!(name);
    }
    save_projects(&projects)
}

fn known_names(root: &Path) -> Result<Vec<String>> {
    let mut vibes = Catalog::load(root)?.vibes()?;
    vibes.sort();
    Ok(vibes.into_iter().map(|(name, _)| name).collect())
}

/// `herdr-alert auto set blocked|done NAME`: record a pick an agent already
/// made itself (its own reasoning, in its own context) -- no subprocess, no
/// network call, no cost beyond the write.
pub fn set(root: &Path, event: &str, name: &str) -> Result<()> {
    if !["blocked", "done"].contains(&event) {
        return Err(usage("usage: herdr-alert auto set blocked|done NAME"));
    }
    let names = known_names(root)?;
    if !valid_name(name) || !names.iter().any(|n| n == name) {
        return Err(usage(format!("Unknown alert: {name}. Run herdr-alert list.")));
    }
    let cwd = env::current_dir().map_err(failure)?;
    let scope = resolve_scope(&cwd)?;
    apply_pick(&scope, &[(event, name)])?;
    println!(
        "{event} set to {name} for branch {} in {}\nPreview: herdr-alert play {name}",
        scope.branch, scope.repo_root
    );
    Ok(())
}

pub struct ProjectStatus {
    pub repo_root: String,
    pub branch: String,
    pub blocked: Option<String>,
    pub done: Option<String>,
}

/// Best-effort, never fails: None when cwd isn't inside a git project, or the
/// cache can't be read -- for `status`/`configure` to show what the hook
/// would actually apply here right now, without their whole display failing
/// just because there is nothing cached yet (or no project at all).
pub fn lookup(cwd: &Path) -> Option<ProjectStatus> {
    let scope = resolve_scope(cwd).ok()?;
    let projects = load_projects().ok()?;
    let entry = &projects[&scope.project_key][&scope.scope_key];
    Some(ProjectStatus {
        repo_root: scope.repo_root,
        branch: scope.branch,
        blocked: entry["blocked"].as_str().map(String::from),
        done: entry["done"].as_str().map(String::from),
    })
}

/// `herdr-alert auto show`: what would actually apply here right now, with
/// no network call and no write -- for checking the project/branch/worktree
/// scoping resolved the way you expect before it fires in a real alert.
pub fn show(_root: &Path) -> Result<()> {
    let cwd = env::current_dir().map_err(failure)?;
    let scope = resolve_scope(&cwd)?;
    let projects = load_projects()?;
    let entry = &projects[&scope.project_key][&scope.scope_key];
    println!("Project:  {}", scope.repo_root);
    println!("Branch:   {}", scope.branch);
    for event in ["blocked", "done"] {
        match entry[event].as_str() {
            Some(name) => println!("  {event:<8} {name}"),
            None => println!("  {event:<8} (not cached; run herdr-alert auto)"),
        }
    }
    Ok(())
}

/// `herdr-alert auto [blocked|done]`: spawn the `claude` CLI to classify this
/// project's branch and recent commits, then save the picks via the same
/// scope-and-cache path `set` uses.
pub fn run(root: &Path, arg: Option<&str>) -> Result<()> {
    let events = Events::parse(arg)?;
    let cwd = env::current_dir().map_err(failure)?;
    let scope = resolve_scope(&cwd)?;
    let commits = git(&cwd, &["log", "-5", "--pretty=%s"]).unwrap_or_default();

    let names = known_names(root)?;
    let catalog = Catalog::load(root)?;
    let mut vibes = catalog.vibes()?;
    vibes.sort();
    let catalog_block = vibes
        .iter()
        .map(|(name, vibe)| format!("- {name}: {vibe}"))
        .collect::<Vec<_>>()
        .join("\n");

    let claude = executable("claude").ok_or_else(|| {
        failure("the `claude` CLI is required for herdr-alert auto. Install Claude Code, or record a pick yourself with herdr-alert auto set blocked|done NAME.")
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
        "Git branch: {}\nRecent commits:\n{}\n\nCatalog:\n{catalog_block}",
        scope.branch,
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
        if !valid_name(name) || !names.iter().any(|n| n == name) {
            return Err(failure(format!("claude picked an unknown alert: {name}")));
        }
        Ok(name.to_owned())
    };
    let blocked = pick("blocked")?;
    let done = pick("done")?;

    let mut updates = Vec::new();
    if events.wants("blocked") {
        updates.push(("blocked", blocked.as_str()));
    }
    if events.wants("done") {
        updates.push(("done", done.as_str()));
    }
    apply_pick(&scope, &updates)?;

    println!("Branch: {}\n", scope.branch);
    for (event, name) in [("blocked", &blocked), ("done", &done)] {
        let saved = if events.wants(event) {
            "saved".to_owned()
        } else {
            format!("not saved; herdr-alert auto {event} to save it")
        };
        println!("  {event:<8} {name:<12} ({saved})");
    }
    println!("\nApplies only to branch {} in {}\nPreview: herdr-alert play {blocked}", scope.branch, scope.repo_root);
    Ok(())
}

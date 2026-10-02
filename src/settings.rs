use crate::{failure, xdg, Result};
use std::{
    collections::BTreeMap,
    env, fs,
    io::Write,
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::{SystemTime, UNIX_EPOCH},
};

const BEGIN: &str = "# >>> herdr-sound >>>";
const END: &str = "# <<< herdr-sound <<<";
const KEYS: &[&str] = &[
    "HERDR_ALERT_BLOCKED",
    "HERDR_ALERT_DONE",
    "HERDR_SOUND_BLOCKED",
    "HERDR_SOUND_DONE",
    "HERDR_VOLUME_BLOCKED",
    "HERDR_VOLUME_DONE",
    "HERDR_ALERT_MAX_SECONDS",
    "HERDR_ALERT_OFF",
    "HERDR_ALERT_FLASH",
    "HERDR_ALERT_SPRITE",
];

fn target() -> Result<PathBuf> {
    Ok(env::var_os("HERDR_PLUGIN_CONFIG_DIR")
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .unwrap_or(
            xdg("XDG_CONFIG_HOME", ".config")?.join("herdr/plugins/config/dev.ariel.herdr-alerts"),
        )
        .join("config.sh"))
}

pub fn config_file(root: &Path) -> Result<PathBuf> {
    let path = target()?;
    if fs::File::open(&path).is_ok() {
        Ok(path)
    } else {
        Ok(root.join("config.sh"))
    }
}

pub struct Config(BTreeMap<String, String>);
impl Config {
    pub fn load(root: &Path) -> Result<Self> {
        // Keep the existing shell configuration contract (including expansions).
        // Only explicitly named sound settings cross the NUL-delimited boundary.
        let variables = KEYS
            .iter()
            .map(|key| format!("\"${{{key}:-}}\" "))
            .collect::<String>();
        let script = format!("root=$2; source \"$1\" >&2 || exit; printf '%s\\0' {variables}");
        let output = Command::new("zsh")
            .args(["-fc", &script, "herdr-sound"])
            .arg(config_file(root)?)
            .arg(root)
            .stderr(Stdio::inherit())
            .output()
            .map_err(failure)?;
        if !output.status.success() {
            return Err(failure("could not load sound configuration"));
        }
        let text = String::from_utf8(output.stdout).map_err(failure)?;
        let values: Vec<_> = text.split_terminator('\0').collect();
        if values.len() != KEYS.len() {
            return Err(failure("invalid sound configuration output"));
        }
        Ok(Self(
            KEYS.iter()
                .zip(values)
                .map(|(&key, value)| (key.to_owned(), value.to_owned()))
                .collect(),
        ))
    }
    pub fn get(&self, key: &str) -> &str {
        self.0.get(key).map(String::as_str).unwrap_or("")
    }
    pub fn flash_enabled(&self) -> bool {
        matches!(self.get("HERDR_ALERT_FLASH"), "" | "1")
    }
}

fn updated(original: &str, updates: &[(String, String)]) -> Result<String> {
    if original.matches(BEGIN).count() != original.matches(END).count()
        || original.matches(BEGIN).count() > 1
    {
        return Err(failure(
            "Malformed herdr-sound settings block; fix it before changing settings.",
        ));
    }
    let start = original.find(BEGIN);
    let end = original.find(END);
    let mut body = if let (Some(start), Some(end)) = (start, end) {
        if end < start {
            return Err(failure("Reversed herdr-sound settings markers."));
        }
        original[start + BEGIN.len()..end]
            .trim_matches('\n')
            .to_owned()
    } else {
        String::new()
    };
    for (key, value) in updates {
        body = body
            .lines()
            .filter(|line| !line.starts_with(&format!("{key}=")))
            .collect::<Vec<_>>()
            .join("\n");
        if !body.is_empty() {
            body.push('\n');
        }
        body += &format!("{key}='{}'", value.replace('\'', "'\\''"));
    }
    let block = format!("{BEGIN}\n{body}\n{END}");
    Ok(if let (Some(start), Some(end)) = (start, end) {
        format!(
            "{}{block}{}",
            &original[..start],
            &original[end + END.len()..]
        )
    } else {
        format!("{}\n\n{block}\n", original.trim_end_matches('\n'))
    })
}

pub fn save(root: &Path, updates: &[(String, String)]) -> Result<()> {
    let mut target = target()?;
    // Follow the file symlink as well as symlinked parent directories, as before.
    for _ in 0..40 {
        if !target.is_symlink() {
            break;
        }
        let link = fs::read_link(&target).map_err(failure)?;
        target = if link.is_absolute() {
            link
        } else {
            target.parent().unwrap().join(link)
        };
    }
    if target.is_symlink() {
        return Err(failure("configuration symlink loop"));
    }
    let defaults = root.join("config.sh");
    let original =
        fs::read_to_string(if target.exists() { &target } else { &defaults }).map_err(failure)?;
    let content = updated(&original, updates)?;
    if target.exists() && content == original {
        return Ok(());
    }
    let parent = target
        .parent()
        .ok_or_else(|| failure("configuration has no parent directory"))?;
    fs::create_dir_all(parent).map_err(failure)?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(failure)?
        .as_nanos();
    let unique = format!("{}.{stamp}", std::process::id());
    let mode = if target.exists() {
        fs::metadata(&target).map_err(failure)?.permissions().mode() & 0o777
    } else {
        0o600
    };
    if target.exists() {
        let backup = parent.join(format!(
            "{}.{}.bak",
            target.file_name().unwrap().to_string_lossy(),
            unique
        ));
        let mut file = fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(backup)
            .map_err(failure)?;
        file.write_all(original.as_bytes()).map_err(failure)?;
        file.sync_all().map_err(failure)?;
    }
    let temporary = parent.join(format!(".herdr-sound-{unique}"));
    let result = (|| {
        let mut file = fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&temporary)?;
        file.write_all(content.as_bytes())?;
        file.set_permissions(fs::Permissions::from_mode(mode))?;
        file.sync_all()?;
        fs::rename(&temporary, &target)
    })();
    let _ = fs::remove_file(temporary);
    result.map_err(failure)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn managed_settings_preserve_user_text_and_refuse_bad_markers() {
        let source = "# custom config\nCUSTOM_SETTING=preserved\n";
        let values = [
            ("HERDR_ALERT_DONE".into(), "1up".into()),
            ("HERDR_SOUND_DONE".into(), "".into()),
        ];
        let result = updated(source, &values).unwrap();
        assert!(result.starts_with(source));
        assert!(result.contains("HERDR_SOUND_DONE=''"));
        assert_eq!(updated(&result, &values).unwrap(), result);
        for bad in [
            BEGIN.to_string(),
            format!("{END}\n{BEGIN}"),
            format!("{BEGIN}\n{END}\n{BEGIN}\n{END}"),
        ] {
            assert!(updated(&bad, &values).is_err());
        }
    }
}

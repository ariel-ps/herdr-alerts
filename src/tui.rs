// Full-screen interactive configuration (`herdr-alert configure`). Reuses the
// same Catalog, settings::Config, and preview() the CLI commands use, so
// anything changed here is readable and settable through the flag-based
// commands too -- this is a second way in, not a second source of truth.
use crate::{auto, executable, failure, preview, settings, valid_name, Catalog, Result};
use crossterm::{
    event::{self, Event, KeyCode, KeyEventKind},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Cell, Paragraph, Row, Table, Tabs},
    Frame, Terminal,
};
use std::{
    env,
    io::{self, Stdout},
    path::{Path, PathBuf},
    time::Duration,
};

#[derive(Clone, Copy, PartialEq, Eq)]
enum Tab {
    Alerts,
    Settings,
    Downloads,
    Status,
}
const TABS: [Tab; 4] = [Tab::Alerts, Tab::Settings, Tab::Downloads, Tab::Status];
impl Tab {
    fn title(self) -> &'static str {
        match self {
            Tab::Alerts => "Alerts",
            Tab::Settings => "Settings",
            Tab::Downloads => "Downloads",
            Tab::Status => "Status",
        }
    }
}

struct AlertRow {
    name: String,
    game: String,
    clip: String,
    ready: bool,
}

struct GameRow {
    name: String,
    sounds_ready: bool,
    sprites_ready: bool,
    has_sprites: bool,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum SettingItem {
    Enabled,
    Flash,
    Sprite,
    Animation,
    VolumeBlocked,
    VolumeDone,
    Duration,
}
const SETTINGS: [SettingItem; 7] = [
    SettingItem::Enabled,
    SettingItem::Flash,
    SettingItem::Sprite,
    SettingItem::Animation,
    SettingItem::VolumeBlocked,
    SettingItem::VolumeDone,
    SettingItem::Duration,
];
impl SettingItem {
    fn label(self) -> &'static str {
        match self {
            SettingItem::Enabled => "Automatic alerts",
            SettingItem::Flash => "Flash",
            SettingItem::Sprite => "Sprite",
            SettingItem::Animation => "Animation",
            SettingItem::VolumeBlocked => "Blocked volume",
            SettingItem::VolumeDone => "Done volume",
            SettingItem::Duration => "Duration limit",
        }
    }
    fn is_toggle(self) -> bool {
        !matches!(
            self,
            SettingItem::VolumeBlocked | SettingItem::VolumeDone | SettingItem::Duration
        )
    }
    fn key(self) -> &'static str {
        match self {
            SettingItem::Enabled => "HERDR_ALERT_OFF",
            SettingItem::Flash => "HERDR_ALERT_FLASH",
            SettingItem::Sprite => "HERDR_ALERT_SPRITE",
            SettingItem::Animation => "HERDR_ALERT_ANIMATION_ENABLED",
            SettingItem::VolumeBlocked => "HERDR_VOLUME_BLOCKED",
            SettingItem::VolumeDone => "HERDR_VOLUME_DONE",
            SettingItem::Duration => "HERDR_ALERT_MAX_SECONDS",
        }
    }
    fn display(self, config: &settings::Config) -> String {
        let raw = config.get(self.key());
        match self {
            SettingItem::Enabled => if raw == "1" { "disabled" } else { "enabled" }.into(),
            SettingItem::Flash | SettingItem::Sprite | SettingItem::Animation => {
                if matches!(raw, "" | "1") { "on" } else { "off" }.into()
            }
            SettingItem::VolumeBlocked => if raw.is_empty() { "1.8" } else { raw }.into(),
            SettingItem::VolumeDone => if raw.is_empty() { "1.0" } else { raw }.into(),
            SettingItem::Duration => {
                if raw.is_empty() {
                    "full".into()
                } else {
                    format!("{raw}s")
                }
            }
        }
    }
}

struct App {
    root: PathBuf,
    tab: Tab,
    alerts: Vec<AlertRow>,
    alert_selected: usize,
    pack_filter: String,
    filtering: bool,
    games: Vec<GameRow>,
    game_selected: usize,
    setting_selected: usize,
    editing: Option<String>,
    message: String,
    quit: bool,
    /// What `herdr-alert auto`/`auto set` has cached for the directory this
    /// TUI was launched from, if any -- computed once, since that cwd can't
    /// change over the TUI's own lifetime.
    project: Option<auto::ProjectStatus>,
}

impl App {
    fn new(root: PathBuf) -> Result<Self> {
        let mut app = Self {
            root,
            tab: Tab::Alerts,
            alerts: Vec::new(),
            alert_selected: 0,
            pack_filter: String::new(),
            filtering: false,
            games: Vec::new(),
            game_selected: 0,
            setting_selected: 0,
            editing: None,
            message: "Tab/Shift+Tab or 1-4 to switch panes. q to quit.".into(),
            quit: false,
            project: env::current_dir().ok().and_then(|cwd| auto::lookup(&cwd)),
        };
        app.reload()?;
        Ok(app)
    }

    fn config(&self) -> Result<settings::Config> {
        settings::Config::load(&self.root)
    }

    fn reload(&mut self) -> Result<()> {
        let catalog = Catalog::load(&self.root)?;
        let alerts_obj = catalog.data["alerts"]
            .as_object()
            .ok_or_else(|| failure("invalid alert catalog"))?;
        let mut rows = Vec::new();
        for name in alerts_obj.keys().filter(|n| !n.starts_with('_')) {
            if let Ok((game, clip)) = catalog.alert(name) {
                rows.push(AlertRow {
                    name: name.clone(),
                    game: game.to_string(),
                    clip: clip.to_string(),
                    ready: catalog.resolve(name).is_ok(),
                });
            }
        }
        rows.sort_by(|a, b| a.name.cmp(&b.name));
        self.alerts = rows;

        let games_obj = catalog.data["games"]
            .as_object()
            .ok_or_else(|| failure("invalid pack catalog"))?;
        let sounds_cache = catalog.cache.clone();
        let sprites_cache = sounds_cache.parent().unwrap().join("sprites");
        let mut games: Vec<_> = games_obj
            .iter()
            .filter(|(name, _)| valid_name(name))
            .map(|(name, spec)| GameRow {
                name: name.clone(),
                sounds_ready: sounds_cache.join(name).join(".done").is_file(),
                has_sprites: spec["sprites"].is_string(),
                sprites_ready: sprites_cache
                    .join(name)
                    .read_dir()
                    .is_ok_and(|mut d| d.next().is_some()),
            })
            .collect();
        games.sort_by(|a, b| a.name.cmp(&b.name));
        self.games = games;

        if self.alert_selected >= self.visible_alerts().len() {
            self.alert_selected = self.visible_alerts().len().saturating_sub(1);
        }
        if self.game_selected >= self.games.len() {
            self.game_selected = self.games.len().saturating_sub(1);
        }
        Ok(())
    }

    fn visible_alerts(&self) -> Vec<&AlertRow> {
        self.alerts
            .iter()
            .filter(|a| self.pack_filter.is_empty() || a.game.contains(self.pack_filter.as_str()))
            .collect()
    }

    fn selected_alert(&self) -> Option<&AlertRow> {
        self.visible_alerts().into_iter().nth(self.alert_selected)
    }

    fn selected_game(&self) -> Option<&GameRow> {
        self.games.get(self.game_selected)
    }
}

type Term = Terminal<CrosstermBackend<Stdout>>;

pub fn run(root: &Path) -> Result<()> {
    if executable("afplay").is_none() && executable("ffplay").is_none() {
        return Err(failure("no audio player found. Install FFmpeg on Linux."));
    }
    let mut terminal = enter().map_err(failure)?;
    let result = (|| -> Result<()> {
        let mut app = App::new(root.to_path_buf())?;
        while !app.quit {
            terminal
                .draw(|frame| draw(frame, &app))
                .map_err(failure)?;
            if event::poll(Duration::from_millis(250)).map_err(failure)? {
                if let Event::Key(key) = event::read().map_err(failure)? {
                    if key.kind == KeyEventKind::Press {
                        handle_key(&mut terminal, &mut app, key.code)?;
                    }
                }
            }
        }
        Ok(())
    })();
    leave(&mut terminal).map_err(failure)?;
    result
}

fn enter() -> io::Result<Term> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    Terminal::new(CrosstermBackend::new(stdout))
}

fn leave(terminal: &mut Term) -> io::Result<()> {
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()
}

/// Drop out of the alternate screen for a blocking external command (preview
/// audio, a download's own progress output) so it gets a normal terminal
/// instead of corrupting the TUI's rendered frame, then come back.
fn suspend<F: FnOnce() -> Result<()>>(terminal: &mut Term, action: F) -> Result<()> {
    leave(terminal).map_err(failure)?;
    let result = action();
    if let Err((_, message)) = &result {
        println!("herdr-alert: {message}");
    }
    println!("\nPress Enter to return to the configure screen...");
    let mut discard = String::new();
    let _ = io::stdin().read_line(&mut discard);
    enable_raw_mode().map_err(failure)?;
    execute!(terminal.backend_mut(), EnterAlternateScreen).map_err(failure)?;
    terminal.clear().map_err(failure)?;
    result
}

fn handle_key(terminal: &mut Term, app: &mut App, key: KeyCode) -> Result<()> {
    if app.filtering {
        match key {
            KeyCode::Esc | KeyCode::Enter => app.filtering = false,
            KeyCode::Backspace => {
                app.pack_filter.pop();
            }
            KeyCode::Char(c) => app.pack_filter.push(c),
            _ => {}
        }
        app.alert_selected = 0;
        return Ok(());
    }
    if let Some(buffer) = app.editing.clone() {
        match key {
            KeyCode::Esc => app.editing = None,
            KeyCode::Enter => {
                commit_edit(app, &buffer)?;
                app.editing = None;
            }
            KeyCode::Backspace => {
                let mut b = buffer;
                b.pop();
                app.editing = Some(b);
            }
            KeyCode::Char(c) if c.is_ascii_digit() || c == '.' => {
                let mut b = buffer;
                b.push(c);
                app.editing = Some(b);
            }
            _ => {}
        }
        return Ok(());
    }
    match key {
        KeyCode::Char('q') | KeyCode::Esc => app.quit = true,
        KeyCode::Tab | KeyCode::Right => {
            let i = TABS.iter().position(|t| *t == app.tab).unwrap();
            app.tab = TABS[(i + 1) % TABS.len()];
        }
        KeyCode::BackTab | KeyCode::Left => {
            let i = TABS.iter().position(|t| *t == app.tab).unwrap();
            app.tab = TABS[(i + TABS.len() - 1) % TABS.len()];
        }
        KeyCode::Char(c @ '1'..='4') => app.tab = TABS[c as usize - '1' as usize],
        KeyCode::Down | KeyCode::Char('j') => move_selection(app, 1),
        KeyCode::Up | KeyCode::Char('k') => move_selection(app, -1),
        _ => match app.tab {
            Tab::Alerts => handle_alerts_key(terminal, app, key)?,
            Tab::Settings => handle_settings_key(app, key)?,
            Tab::Downloads => handle_downloads_key(terminal, app, key)?,
            Tab::Status => {}
        },
    }
    Ok(())
}

fn move_selection(app: &mut App, delta: isize) {
    match app.tab {
        Tab::Alerts => {
            let len = app.visible_alerts().len();
            if len > 0 {
                app.alert_selected =
                    ((app.alert_selected as isize + delta).rem_euclid(len as isize)) as usize;
            }
        }
        Tab::Settings => {
            app.setting_selected =
                ((app.setting_selected as isize + delta).rem_euclid(SETTINGS.len() as isize))
                    as usize;
        }
        Tab::Downloads => {
            let len = app.games.len();
            if len > 0 {
                app.game_selected =
                    ((app.game_selected as isize + delta).rem_euclid(len as isize)) as usize;
            }
        }
        Tab::Status => {}
    }
}

fn handle_alerts_key(terminal: &mut Term, app: &mut App, key: KeyCode) -> Result<()> {
    let Some(name) = app.selected_alert().map(|a| a.name.clone()) else {
        return Ok(());
    };
    match key {
        KeyCode::Char('/') => app.filtering = true,
        KeyCode::Enter => {
            suspend(terminal, || preview(&app.root, Some(name.as_str()), false))?;
        }
        KeyCode::Char('b') => {
            settings::save(
                &app.root,
                &[
                    ("HERDR_ALERT_BLOCKED".into(), name.clone()),
                    ("HERDR_SOUND_BLOCKED".into(), String::new()),
                ],
            )?;
            app.message = format!("Blocked sound set to {name}.");
        }
        KeyCode::Char('d') => {
            settings::save(
                &app.root,
                &[
                    ("HERDR_ALERT_DONE".into(), name.clone()),
                    ("HERDR_SOUND_DONE".into(), String::new()),
                ],
            )?;
            app.message = format!("Done sound set to {name}.");
        }
        KeyCode::Char('B') | KeyCode::Char('D') => {
            let catalog = Catalog::load(&app.root)?;
            let event = if key == KeyCode::Char('B') { "BLOCKED" } else { "DONE" };
            match catalog.alert_sprite(&name) {
                Ok((game, sprite)) => {
                    settings::save(
                        &app.root,
                        &[(format!("HERDR_SPRITE_{event}"), format!("{game}:{sprite}"))],
                    )?;
                    app.message = format!("{event} sprite set to {name}'s ({sprite}).");
                }
                Err(_) => app.message = format!("'{name}' has no sprite of its own."),
            }
        }
        _ => {}
    }
    Ok(())
}

fn handle_settings_key(app: &mut App, key: KeyCode) -> Result<()> {
    let item = SETTINGS[app.setting_selected];
    if key != KeyCode::Enter {
        return Ok(());
    }
    if item.is_toggle() {
        let config = app.config()?;
        let current = config.get(item.key());
        let now_on = matches!(current, "" | "1");
        let value = if item == SettingItem::Enabled {
            // Enabled is the inverse of HERDR_ALERT_OFF.
            if now_on { "0" } else { "1" }
        } else if now_on {
            "0"
        } else {
            "1"
        };
        settings::save(&app.root, &[(item.key().into(), value.into())])?;
        app.message = format!("{} updated.", item.label());
    } else {
        app.editing = Some(String::new());
    }
    Ok(())
}

fn commit_edit(app: &mut App, buffer: &str) -> Result<()> {
    let item = SETTINGS[app.setting_selected];
    let value = if buffer.is_empty() {
        String::new()
    } else {
        let parsed = buffer
            .parse::<f64>()
            .ok()
            .filter(|v| v.is_finite() && *v >= 0.0);
        match parsed {
            Some(v) => v.to_string(),
            None => {
                app.message = "Enter a nonnegative number, or leave blank for the default.".into();
                return Ok(());
            }
        }
    };
    settings::save(&app.root, &[(item.key().into(), value)])?;
    app.message = format!("{} updated.", item.label());
    Ok(())
}

fn handle_downloads_key(terminal: &mut Term, app: &mut App, key: KeyCode) -> Result<()> {
    if key != KeyCode::Enter {
        return Ok(());
    }
    let Some(game) = app.selected_game().map(|g| g.name.clone()) else {
        return Ok(());
    };
    let root = app.root.clone();
    suspend(terminal, || {
        println!("Downloading {game}...\n");
        Catalog::load(&root)?.download(&root, std::slice::from_ref(&game), false)
    })?;
    app.reload()?;
    Ok(())
}

fn draw(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(3), Constraint::Min(0), Constraint::Length(1)])
        .split(area);
    draw_tabs(frame, chunks[0], app.tab);
    match app.tab {
        Tab::Alerts => draw_alerts(frame, chunks[1], app),
        Tab::Settings => draw_settings(frame, chunks[1], app),
        Tab::Downloads => draw_downloads(frame, chunks[1], app),
        Tab::Status => draw_status(frame, chunks[1], app),
    }
    draw_statusline(frame, chunks[2], app);
}

fn draw_tabs(frame: &mut Frame, area: Rect, active: Tab) {
    let titles: Vec<Line> = TABS.iter().map(|t| Line::from(t.title())).collect();
    let tabs = Tabs::new(titles)
        .block(Block::default().borders(Borders::ALL).title("Herdr Alert — configure"))
        .select(TABS.iter().position(|t| *t == active).unwrap_or(0))
        .highlight_style(Style::default().add_modifier(Modifier::BOLD).fg(Color::Cyan));
    frame.render_widget(tabs, area);
}

fn draw_statusline(frame: &mut Frame, area: Rect, app: &App) {
    let hint = match app.tab {
        Tab::Alerts if app.filtering => {
            format!("Filter by pack: {}_  (Enter/Esc to stop)", app.pack_filter)
        }
        Tab::Alerts => "Enter preview  b/d set blocked/done sound  B/D set blocked/done sprite  / filter"
            .to_string(),
        Tab::Settings if app.editing.is_some() => {
            format!(
                "{}: {}_  (Enter to save, Esc to cancel, blank = default)",
                SETTINGS[app.setting_selected].label(),
                app.editing.as_deref().unwrap_or("")
            )
        }
        Tab::Settings => "Enter toggles on/off, or opens numeric entry".to_string(),
        Tab::Downloads => "Enter downloads the selected pack".to_string(),
        Tab::Status => String::new(),
    };
    let line = if hint.is_empty() {
        app.message.clone()
    } else {
        format!("{hint}    {}", app.message)
    };
    frame.render_widget(Paragraph::new(line).style(Style::default().fg(Color::DarkGray)), area);
}

fn draw_alerts(frame: &mut Frame, area: Rect, app: &App) {
    let rows: Vec<Row> = app
        .visible_alerts()
        .iter()
        .enumerate()
        .map(|(i, a)| {
            let style = if i == app.alert_selected {
                Style::default().add_modifier(Modifier::REVERSED)
            } else {
                Style::default()
            };
            Row::new(vec![
                Cell::from(a.name.clone()),
                Cell::from(a.game.clone()),
                Cell::from(if a.ready { "ready" } else { "missing" }),
                Cell::from(if a.clip.is_empty() { "(any)".into() } else { a.clip.clone() }),
            ])
            .style(style)
        })
        .collect();
    let table = Table::new(
        rows,
        [
            Constraint::Length(14),
            Constraint::Length(14),
            Constraint::Length(10),
            Constraint::Min(10),
        ],
    )
    .header(Row::new(["SOUND", "PACK", "STATUS", "CLIP"]).style(Style::default().add_modifier(Modifier::BOLD)))
    .block(Block::default().borders(Borders::ALL));
    frame.render_widget(table, area);
}

fn draw_settings(frame: &mut Frame, area: Rect, app: &App) {
    let config = match app.config() {
        Ok(c) => c,
        Err(_) => return,
    };
    let rows: Vec<Row> = SETTINGS
        .iter()
        .enumerate()
        .map(|(i, item)| {
            let style = if i == app.setting_selected {
                Style::default().add_modifier(Modifier::REVERSED)
            } else {
                Style::default()
            };
            let value = if i == app.setting_selected {
                app.editing.clone().unwrap_or_else(|| item.display(&config))
            } else {
                item.display(&config)
            };
            Row::new(vec![Cell::from(item.label()), Cell::from(value)]).style(style)
        })
        .collect();
    let table = Table::new(rows, [Constraint::Length(20), Constraint::Min(10)])
        .block(Block::default().borders(Borders::ALL).title("Settings"));
    frame.render_widget(table, area);
}

fn draw_downloads(frame: &mut Frame, area: Rect, app: &App) {
    let rows: Vec<Row> = app
        .games
        .iter()
        .enumerate()
        .map(|(i, g)| {
            let style = if i == app.game_selected {
                Style::default().add_modifier(Modifier::REVERSED)
            } else {
                Style::default()
            };
            Row::new(vec![
                Cell::from(g.name.clone()),
                Cell::from(if g.sounds_ready { "ready" } else { "not downloaded" }),
                Cell::from(if !g.has_sprites {
                    "n/a"
                } else if g.sprites_ready {
                    "ready"
                } else {
                    "not downloaded"
                }),
            ])
            .style(style)
        })
        .collect();
    let table = Table::new(
        rows,
        [Constraint::Length(16), Constraint::Length(16), Constraint::Length(16)],
    )
    .header(Row::new(["PACK", "SOUNDS", "SPRITES"]).style(Style::default().add_modifier(Modifier::BOLD)))
    .block(Block::default().borders(Borders::ALL));
    frame.render_widget(table, area);
}

fn draw_status(frame: &mut Frame, area: Rect, app: &App) {
    let Ok(config) = app.config() else { return };
    let mut lines = vec![
        Line::from(Span::styled(
            "Herdr Alert",
            Style::default().add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
    ];
    for item in SETTINGS {
        lines.push(Line::from(format!("{:<18} {}", item.label(), item.display(&config))));
    }
    if let Some(p) = &app.project {
        lines.push(Line::from(format!("{:<18} {} (branch {})", "Project", p.repo_root, p.branch)));
    }
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "Alerts",
        Style::default().add_modifier(Modifier::BOLD),
    )));
    for event in ["blocked", "done"] {
        let upper = event.to_uppercase();
        let mut name = config.get(&format!("HERDR_ALERT_{upper}")).to_string();
        if name.is_empty() {
            if let Ok(catalog) = Catalog::load(&app.root) {
                name = catalog.data["states"][event].as_str().unwrap_or("").to_string();
            }
        }
        let sprite_override = config.get(&format!("HERDR_SPRITE_{upper}"));
        let mut text = format!("{event:<10} {name}");
        if !sprite_override.is_empty() {
            text += &format!("  (sprite: {sprite_override})");
        }
        let project_pick = app.project.as_ref().and_then(|p| {
            if event == "blocked" { p.blocked.as_ref() } else { p.done.as_ref() }
        });
        if let Some(pick) = project_pick {
            text += &format!("  (project override: {pick})");
        }
        lines.push(Line::from(text));
    }
    frame.render_widget(
        Paragraph::new(lines).block(Block::default().borders(Borders::ALL)),
        area,
    );
}

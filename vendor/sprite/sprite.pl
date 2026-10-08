#!/usr/bin/env perl
# kitty-sprite.pl — play a Red Alert style "unit ready" sprite in the top-right
# corner of a kitty pane, then take it away again.
#
# Draws with kitty's graphics protocol rather than by printing characters, which
# is what makes it safe over a full-screen TUI like Claude Code: the sprite is
# an image floating at z=1 above the cells, the text underneath is never
# touched, and deleting the image at the end puts the pane back exactly as it
# was. Printing a sprite would instead overwrite whatever is on those cells,
# and nothing would repaint scrollback afterwards.
#
# perl, not python: alerts are usually fired by an agent, and inside Claude Code
# `python3` resolves to a shim that refuses to run (the same trap that broke
# flash-term's colour restore). perl has no such problem and MIME::Base64 is
# core.
#
# usage: kitty-sprite.pl <tty> <cols> [pixels]

use strict;
use warnings;
use MIME::Base64 qw(encode_base64);
use JSON::PP ();
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC);

my ($tty, $cols, $px) = @ARGV;
die "usage: $0 <tty> <cols> [pixels]\n" unless $tty && $cols;

# Sized in pixels, deliberately not in cells. Scaling into a cell box (c=/r=)
# squashes the disc into an ellipse whenever the font's cell aspect isn't what
# the box assumed, and the cell size can't be discovered from here: `kitty @ ls`
# doesn't report it, and asking the terminal directly (CSI 16 t) would send the
# reply to whatever owns the pty — i.e. straight into Claude Code's input.
my $PX      = $px || 40;
my ($WIDTH, $HEIGHT) = ($PX, $PX);
my $FRAMES  = 8;       # build-up sweep, like the sidebar clock wipe
my $PULSES  = 3;       # then the ready flash
my $DELAY   = 0.055;

# Red Alert sidebar palette: amber on near-black, white-hot on the flash.
my @DARK   = (32, 16, 0);
my @AMBER  = (255, 176, 0);
my @HOT    = (255, 244, 208);

# One frame as raw RGBA. $wipe is how far round the sweep has gone (0..1);
# $hot fills the whole disc with the flash colour instead.
sub frame {
    my ($wipe, $hot) = @_;
    my $c = ($PX - 1) / 2;
    my $r = $PX / 2 - 1;
    my $px = '';
    for my $y (0 .. $PX - 1) {
        for my $x (0 .. $PX - 1) {
            my ($dx, $dy) = ($x - $c, $y - $c);
            my $d = sqrt($dx * $dx + $dy * $dy);
            if ($d > $r) {                      # outside the disc: see-through
                $px .= pack 'C4', 0, 0, 0, 0;
                next;
            }
            my @rgb;
            if ($d > $r - 2.2) {                # rim
                @rgb = $hot ? @HOT : @AMBER;
            } elsif ($hot) {
                @rgb = @HOT;
            } else {
                # atan2(dx, -dy) puts 0 at 12 o'clock and grows clockwise.
                my $ang = atan2($dx, -$dy);
                $ang += 2 * 3.14159265358979 if $ang < 0;
                @rgb = $ang <= $wipe * 2 * 3.14159265358979 ? @AMBER : @DARK;
            }
            $px .= pack 'C4', @rgb, 255;
        }
    }
    return $px;
}

# Upload all frames once as a tiled image. Playback changes only the crop of
# one placement, so neither Kitty nor a multiplexer has to replace a live image.
my $atlas_columns;
sub upload_frames {
    my ($fh, $frames, $id) = @_;
    $atlas_columns = int(sqrt(@$frames * $HEIGHT / $WIDTH)) || 1;
    $atlas_columns = @$frames if $atlas_columns > @$frames;
    my $rows = int((@$frames + $atlas_columns - 1) / $atlas_columns);
    my $atlas_width = $atlas_columns * $WIDTH;
    my $atlas_height = $rows * $HEIGHT;
    my $data = '';
    for my $row (0 .. $rows - 1) {
        for my $y (0 .. $HEIGHT - 1) {
            for my $column (0 .. $atlas_columns - 1) {
                my $frame = $frames->[$row * $atlas_columns + $column];
                $data .= defined($frame) ? substr($frame, $y * $WIDTH * 4, $WIDTH * 4)
                                        : "\0" x ($WIDTH * 4);
            }
        }
    }
    my $b64 = encode_base64($data, '');
    my @chunks = $b64 =~ /(.{1,4000})/gs;
    for my $i (0 .. $#chunks) {
        my $ctrl = $i == 0
            ? "a=t,f=32,s=$atlas_width,v=$atlas_height,i=$id,q=2"
            : "q=2";
        my $more = $i < $#chunks ? 1 : 0;
        print $fh "\033_G$ctrl,m=$more;$chunks[$i]\033\\";
    }
}

sub show_frame {
    my ($fh, $index, $id, $row, $col) = @_;
    my $x = ($index % $atlas_columns) * $WIDTH;
    my $y = int($index / $atlas_columns) * $HEIGHT;
    print $fh "\033[s\033[${row};${col}H"
        . "\033_Ga=p,i=$id,p=1,x=$x,y=$y,w=$WIDTH,h=$HEIGHT,C=1,z=1,q=2\033\\\033[u";
}

# Real Red Alert frames, when a pack is present. Packs are built by
# alert8-sync from the game's own SHP archives and land in the same cache tree
# as the sounds; the procedural disc below stays as the fallback so this still
# works on a machine that never synced.
sub load_pack {
    my $dir = $ENV{SPRITE_DIR} || "$ENV{HOME}/.cache/dev-env-alert/sprites";
    # Packs live per game (sprites/<game>/*.rgba) so the sprite always matches
    # the sound that fired it. SPRITE_GAME picks the game; a game with no art
    # of its own (sprites: null in packs.json, e.g. kirby/metalgear/doom) gets
    # no sprite at all here and falls through to the generic procedural disc
    # below, never another game's character.
    my @dirs = grep { -d } ($ENV{SPRITE_GAME} ? "$dir/$ENV{SPRITE_GAME}" : glob("$dir/*/"));
    my @packs;
    for my $d (@dirs) {
        @packs = $ENV{SPRITE_NAME} ? ("$d/$ENV{SPRITE_NAME}.rgba")
                                   : glob("$d/*.rgba");
        @packs = grep { -r $_ } @packs;
        last if @packs;
    }
    @packs = ($ENV{SPRITE_FILE}) if $ENV{SPRITE_FILE};
    return unless @packs;
    open my $in, '<:raw', $packs[int rand @packs] or return invalid_pack();
    read($in, my $hdr, 8) == 8 or return invalid_pack();
    # Version 0 is the original raw pack. Version 1 prefixes each frame with
    # its u16 duration in milliseconds and plays without a gap between cycles.
    my ($n, $w, $h, $version) = unpack 'v4', $hdr;
    return invalid_pack() unless $n && $n <= 600 && $w && $h
        && $w <= 512 && $h <= 512 && $version <= 1;
    my $size = 8 + $n * ($w * $h * 4 + ($version ? 2 : 0));
    return invalid_pack() unless $size <= 64 * 1024 * 1024 && -s $in == $size;
    my (@f, @delays);
    my $duration = 0;
    for (1 .. $n) {
        my $ms = 55;
        if ($version) {
            read($in, my $timing, 2) == 2 or return invalid_pack();
            $ms = unpack 'v', $timing;
            return invalid_pack() unless $ms >= 10 && $ms <= 10000;
        }
        $duration += $ms;
        read($in, my $buf, $w * $h * 4) == $w * $h * 4 or return invalid_pack();
        push @f, $buf;
        push @delays, $ms / 1000;
    }
    close $in;
    return invalid_pack() if $version && $duration > 30000;
    # Packs are baked at whatever size they were built; scaling here rather
    # than rebuilding them means one knob covers every pack, present and future.
    my $side = $w > $h ? $w : $h;
    my $target;
    if ($ENV{SPRITE_FULLSCREEN}) {
        # True pixel dimensions aren't knowable here (see the file header), so
        # this uses the same kind of rough per-cell heuristic already used
        # below for corner placement: ~7px/column, and a commonly-typical
        # ~15px/row for a monospace terminal's taller cell. Good enough to
        # fill most of the pane without the terminal's exact font metrics.
        my $avail_w = ($cols - 4) * 7;
        my $avail_h = (($ENV{SPRITE_ROWS} || 24) - 4) * 15;
        $target = $avail_w < $avail_h ? $avail_w : $avail_h;
        $target = 512 if $target > 512;
        $target = 16 if $target < 16;
    } else {
        $target = $ENV{SPRITE_PX} || ($version ? ($side > 192 ? 192 : $side) : 52);
    }
    return invalid_pack() unless $target =~ /^\d+$/ && $target >= 1 && $target <= 512;
    my ($tw, $th) = (int($w * $target / $side) || 1, int($h * $target / $side) || 1);
    return invalid_pack() if $n * $tw * $th * 4 > 64 * 1024 * 1024;
    if ($tw != $w || $th != $h) {
        @f = map { scale_frame($_, $w, $h, $tw, $th) } @f;
    }
    if (my $bg = background_buffer($tw, $th)) {
        @f = map { composite_background($_, $bg) } @f;
    } elsif ($ENV{SPRITE_BACKDROP} // !$version) {
        @f = map { backdrop($_) } @f;
    }
    return ($tw, $th, \@f, \@delays, $version);
}

# Nearest-neighbour resize of one RGBA frame. Nearest on purpose: these
# are pixel-art sprites, and interpolating turns them to mush.
sub scale_frame {
    my ($buf, $w, $h, $tw, $th) = @_;
    my $out = '';
    for my $y (0 .. $th - 1) {
        my $sy = int($y * $h / $th);
        for my $x (0 .. $tw - 1) {
            $out .= substr($buf, (($sy * $w) + int($x * $w / $tw)) * 4, 4);
        }
    }
    return $out;
}

# Fill the see-through pixels with solid black. A unit sprite is mostly
# transparent, and over a busy TUI that reads as noise rather than as a marker;
# a filled square makes it obviously deliberate. SPRITE_BACKDROP=0 to keep the
# sprite floating on the text.
sub backdrop {
    my @p = unpack 'C*', $_[0];
    for (my $i = 0; $i < @p; $i += 4) {
        @p[$i .. $i + 3] = (0, 0, 0, 255) if $p[$i + 3] == 0;
    }
    return pack 'C*', @p;
}

sub invalid_pack {
    warn "herdr-alert: animation is missing or invalid; using fallback artwork. Reimport it with herdr-alert set animation FILE.gif.\n";
    return;
}

# Original, generic backdrops a sprite can play over -- flat colour,
# gradients, or a simple generated pattern, picked with
# `herdr-alert set background NAME` (data/packs.json's "backgrounds"). Not
# game art, so these are drawn procedurally at whatever size the sprite box
# ends up being, the same way the fallback disc above is, rather than being a
# file anyone has to fetch.
my %BACKGROUNDS = (
    sky   => sub { bg_gradient([96, 150, 224], [198, 224, 246], @_) },
    dusk  => sub { bg_gradient([255, 150, 96], [48, 32, 76], @_) },
    night => sub { bg_stars(@_) },
    grid  => sub { bg_grid(@_) },
    solid => sub { bg_solid([28, 28, 32], @_) },
    hills => sub { bg_hills(@_) },
);

sub bg_gradient {
    my ($top, $bottom, $w, $h) = @_;
    my $px = '';
    for my $y (0 .. $h - 1) {
        my $t = $h > 1 ? $y / ($h - 1) : 0;
        my @rgb = map { int($top->[$_] + ($bottom->[$_] - $top->[$_]) * $t) } 0 .. 2;
        $px .= pack('C4', @rgb, 255) x $w;
    }
    return $px;
}

sub bg_solid {
    my ($rgb, $w, $h) = @_;
    return pack('C4', @$rgb, 255) x ($w * $h);
}

# A fixed small LCG rather than Perl's rand: the same name should look the
# same every time, not reseed from the clock on every alert.
sub bg_stars {
    my ($w, $h) = @_;
    my @px = unpack 'C*', bg_gradient([8, 8, 20], [28, 22, 48], $w, $h);
    my $seed = 7;
    for (1 .. int($w * $h / 24)) {
        $seed = ($seed * 1103515245 + 12345) & 0x7fffffff;
        my $x = $seed % $w;
        $seed = ($seed * 1103515245 + 12345) & 0x7fffffff;
        my $y = $seed % $h;
        my $i = ($y * $w + $x) * 4;
        @px[$i .. $i + 3] = (235, 235, 255, 255);
    }
    return pack 'C*', @px;
}

sub bg_grid {
    my ($w, $h) = @_;
    my $step = $w >= 8 ? int($w / 8) : 1;
    my $px = '';
    for my $y (0 .. $h - 1) {
        for my $x (0 .. $w - 1) {
            my $on_line = ($x % $step == 0) || ($y % $step == 0);
            $px .= $on_line ? pack('C4', 54, 64, 78, 255) : pack('C4', 20, 22, 28, 255);
        }
    }
    return $px;
}

sub hill_height {
    my ($x, $cx, $r, $amp) = @_;
    my $dx = ($x - $cx) / $r;
    return 0 if abs($dx) >= 1;
    return $amp * sqrt(1 - $dx * $dx);
}

# A generic rolling-hills landscape: two plain dome-shaped silhouettes (not
# any particular game's bush/cloud shapes) over a flat ground strip.
sub bg_hills {
    my ($w, $h) = @_;
    my $horizon = int($h * 0.78);
    $horizon = $h - 1 if $horizon >= $h;
    my @far  = ($w * 0.72, $w * 0.46, $h * 0.13, [120, 168, 132]);
    my @near = ($w * 0.28, $w * 0.40, $h * 0.18, [70, 132, 84]);
    my (@far_h, @near_h);
    for my $x (0 .. $w - 1) {
        $far_h[$x]  = hill_height($x, @far[0 .. 2]);
        $near_h[$x] = hill_height($x, @near[0 .. 2]);
    }
    my $px = '';
    for my $y (0 .. $h - 1) {
        if ($y > $horizon) {
            $px .= pack('C4', 58, 100, 60, 255) x $w;
            next;
        }
        my $t = $horizon > 0 ? $y / $horizon : 0;
        my @sky = (int(150 + (225 - 150) * $t), int(190 + (235 - 190) * $t), int(230 + (245 - 230) * $t));
        for my $x (0 .. $w - 1) {
            my @rgb = $y >= $horizon - $near_h[$x] ? @{ $near[3] }
                    : $y >= $horizon - $far_h[$x]  ? @{ $far[3] }
                    : @sky;
            $px .= pack('C4', @rgb, 255);
        }
    }
    return $px;
}

sub background_buffer {
    my ($w, $h) = @_;
    my $name = $ENV{BACKGROUND_NAME} or return;
    my $gen = $BACKGROUNDS{$name} or return;
    return $gen->($w, $h);
}

# Fills only the see-through pixels, so the sprite's own art always wins.
sub composite_background {
    my ($frame, $bg) = @_;
    my @p = unpack 'C*', $frame;
    my @b = unpack 'C*', $bg;
    for (my $i = 0; $i < @p; $i += 4) {
        @p[$i .. $i + 3] = @b[$i .. $i + 3] if $p[$i + 3] == 0;
    }
    return pack 'C*', @p;
}

my ($pack_w, $pack_h, $pack_frames, $pack_delays, $timed) = load_pack();
($WIDTH, $HEIGHT) = ($pack_w, $pack_h) if $pack_frames;
my $legacy_pack = $pack_frames && !$timed;
unless ($pack_frames) {
    $pack_frames = [map { frame($_ / $FRAMES, 0) } 1 .. $FRAMES];
    $pack_delays = [($DELAY) x $FRAMES];
    for (1 .. $PULSES) {
        push @$pack_frames, frame(1, 1), frame(1, 0);
        push @$pack_delays, ($DELAY * 1.6) x 2;
    }
}

open my $fh, '>', $tty or die "open $tty: $!\n";
select((select($fh), $| = 1)[0]);

# Keep clear of the right edge, scaled to the sprite: a cell is roughly 7px
# wide at any sane font size, so this stays a shade wider than the image and
# tucks into the corner without being clipped. A fullscreen scene centers
# instead, using the same rough per-cell heuristic as its own sizing above.
my ($col, $row);
if ($ENV{SPRITE_FULLSCREEN}) {
    my $rows_n = $ENV{SPRITE_ROWS} || 24;
    my $width_cols = int($WIDTH / 7) || 1;
    my $height_rows = int($HEIGHT / 15) || 1;
    $col = int(($cols - $width_cols) / 2) + 1;
    $row = int(($rows_n - $height_rows) / 2) + 1;
    $col = 1 if $col < 1;
    $row = 1 if $row < 1;
} else {
    $col = $cols - (int($WIDTH / 7) + 1);
    $col = 1 if $col < 1;
    $row = 1;
}
# Keyed on the window, not the pid, so a second alert replaces the sprite still
# sitting in that pane instead of stacking a new image on top of it.
my $id = 7000 + (($ENV{KITTY_WINDOW_ID} || $$) % 900);
upload_frames($fh, $pack_frames, $id);

# One complete animation pass; repeated passes can stop promptly on focus.
sub play_once {
    my ($out, $deadline) = @_;
    my $spent = 0;
    # Legacy short sprites remain visible for about a second. Always play
    # whole cycles, including long scenes; imported scenes own their timing.
    my $n = scalar @$pack_frames;
    $n *= int((16 + $n - 1) / $n) if $legacy_pack && $n < 16;
    my $next_focus_check = 0;
    for my $i (0 .. $n - 1) {
        show_frame($out, $i % @$pack_frames, $id, $row, $col);
        my $delay = $pack_delays->[$i % @$pack_frames];
        my $until = clock_gettime(CLOCK_MONOTONIC) + $delay;
        while (1) {
            my $now = clock_gettime(CLOCK_MONOTONIC);
            if (defined $deadline && $now >= $next_focus_check) {
                my $focused = window_focused();
                return if !defined($focused) || $focused || $now >= $deadline;
                $next_focus_check = $now + 0.15;
            }
            my $remaining = $until - clock_gettime(CLOCK_MONOTONIC);
            last if $remaining <= 0;
            select(undef, undef, undef, defined($deadline) && $remaining > 0.05 ? 0.05 : $remaining);
        }
        $spent += $delay;
    }
    return $spent;
}

# Keep the animation running as an "I finished, you weren't here" marker and
# clear it when you come back. kitty has no keystroke event (see
# kitty-flash-watcher.py), so focus is the closest signal to "you typed in this
# pane". A focused pane clears after one animation.
# `kitty @ ls --match` still prints the whole OS-window/tab tree, so this walks
# to the window itself rather than pattern-matching the blob. JSON::PP is core.
#
# All three levels matter. A window keeps is_focused while it is merely the
# active window *of its tab*, so checking that alone reports "focused" for a
# pane sitting in a hidden tab, or in a kitty that isn't even the frontmost
# app — which is exactly when the sprite should still be running.
sub kitty_window_focused {
    my $wid = $ENV{KITTY_WINDOW_ID} or return;
    my $out = qx{kitty \@ ls 2>/dev/null} or return;
    my $data = eval { JSON::PP::decode_json($out) } or return;
    for my $osw (@$data) {
        for my $tab (@{ $osw->{tabs} || [] }) {
            for my $w (@{ $tab->{windows} || [] }) {
                next unless ($w->{id} // -1) == $wid;
                return ($osw->{is_focused} && $tab->{is_active}
                        && $w->{is_focused}) ? 1 : 0;
            }
        }
    }
    return;
}

sub window_focused {
    my $pane = $ENV{SPRITE_PANE_ID};
    return kitty_window_focused() unless $pane;
    # Herdr panes share the outer terminal window. Its focus alone cannot tell
    # whether the user has returned to the pane that raised the alert.
    open my $pipe, '-|', ($ENV{HERDR_BIN_PATH} || 'herdr'), 'pane', 'get', $pane
        or return;
    my $out = do { local $/; <$pipe> };
    close $pipe or return;
    my $data = eval { JSON::PP::decode_json($out) } or return;
    my $focused = $data->{result}{pane}{focused};
    return unless defined $focused;
    return 0 unless $focused;
    my $outer = kitty_window_focused();
    return defined($outer) ? $outer : 1;
}

# Always show one animation, then wait only if the pane is unfocused. Checking
# afterwards also catches switching away while a manual preview is playing.
play_once($fh);
my $loop = $ENV{SPRITE_PERSIST} // 1;
my $focused = $loop ? window_focused() : undef;
my $persist = $loop && defined($focused) && !$focused;
warn "herdr-alert: focus tracking is unavailable; sprite will play once.\n"
    if $loop && !defined($focused);

if ($persist) {
    close $fh;
    exit 0 if fork();                       # parent returns, sprite keeps going
    # Child: loop until focus returns. Long scenes check focus during playback
    # so returning does not require waiting for the rest of the cycle.
    my $ttl = $ENV{SPRITE_TTL} || 1800;
    my $gap = $ENV{SPRITE_LOOP_GAP} // ($timed ? 0 : 0.6);
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + $ttl;
    open my $out, '>', $tty or exit 0;
    select((select($out), $| = 1)[0]);
    while (clock_gettime(CLOCK_MONOTONIC) < $deadline) {
        my $focused = window_focused();
        last unless defined($focused); # stop if the pane was closed
        last if $focused;
        last unless defined play_once($out, $deadline);
        select(undef, undef, undef, $gap);
    }
    print $out "\033_Ga=d,d=I,i=$id,q=2\033\\";
    close $out;
    exit 0;
}

print $fh "\033_Ga=d,d=I,i=$id,q=2\033\\";
close $fh;

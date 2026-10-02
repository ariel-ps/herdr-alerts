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

my ($tty, $cols, $px) = @ARGV;
die "usage: $0 <tty> <cols> [pixels]\n" unless $tty && $cols;

# Sized in pixels, deliberately not in cells. Scaling into a cell box (c=/r=)
# squashes the disc into an ellipse whenever the font's cell aspect isn't what
# the box assumed, and the cell size can't be discovered from here: `kitty @ ls`
# doesn't report it, and asking the terminal directly (CSI 16 t) would send the
# reply to whatever owns the pty — i.e. straight into Claude Code's input.
my $PX      = $px || 40;
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

# Transmit + place at the cursor. Same image id and placement id every frame, so
# each one replaces the last instead of stacking placements up.
sub send_frame {
    my ($fh, $data, $id, $row, $col) = @_;
    my $b64 = encode_base64($data, '');
    my @chunks = $b64 =~ /(.{1,4000})/gs;
    print $fh "\033[s\033[${row};${col}H";
    for my $i (0 .. $#chunks) {
        my $ctrl = $i == 0
            ? "a=T,f=32,s=$PX,v=$PX,C=1,z=1,i=$id,p=1,q=2"
            : "q=2";
        my $more = $i < $#chunks ? 1 : 0;
        print $fh "\033_G$ctrl,m=$more;$chunks[$i]\033\\";
    }
    print $fh "\033[u";
}

# Real Red Alert frames, when a pack is present. Packs are built by
# alert8-sync from the game's own SHP archives and land in the same cache tree
# as the sounds; the procedural disc below stays as the fallback so this still
# works on a machine that never synced.
sub load_pack {
    my $dir = $ENV{SPRITE_DIR} || "$ENV{HOME}/.cache/dev-env-alert/sprites";
    # Packs live per game (sprites/<game>/*.rgba) so the sprite can match the
    # sound that fired it. SPRITE_GAME picks the game; a game with no art of
    # its own borrows from whatever is synced rather than dropping to the disc.
    my @dirs = grep { -d } ($ENV{SPRITE_GAME} ? "$dir/$ENV{SPRITE_GAME}" : (),
                            glob("$dir/*/"), $dir);
    my @packs;
    for my $d (@dirs) {
        @packs = $ENV{SPRITE_NAME} ? ("$d/$ENV{SPRITE_NAME}.rgba")
                                   : glob("$d/*.rgba");
        @packs = grep { -r $_ } @packs;
        last if @packs;
    }
    return unless @packs;
    open my $in, '<:raw', $packs[int rand @packs] or return;
    read($in, my $hdr, 8) == 8 or return;
    my ($n, $w, $h) = unpack 'v3', $hdr;
    return unless $n && $w && $w == $h;
    my @f;
    for (1 .. $n) {
        read($in, my $buf, $w * $h * 4) == $w * $h * 4 or last;
        push @f, $buf;
    }
    close $in;
    return unless @f;
    # Packs are baked at whatever size they were built; scaling here rather
    # than rebuilding them means one knob covers every pack, present and future.
    my $target = $ENV{SPRITE_PX} || 52;
    if ($target != $w) {
        @f = map { scale_frame($_, $w, $target) } @f;
        $w = $target;
    }
    @f = map { backdrop($_) } @f unless defined $ENV{SPRITE_BACKDROP}
                                        && !$ENV{SPRITE_BACKDROP};
    return ($w, \@f);
}

# Nearest-neighbour resize of one square RGBA frame. Nearest on purpose: these
# are pixel-art sprites, and interpolating turns them to mush.
sub scale_frame {
    my ($buf, $from, $to) = @_;
    my $out = '';
    for my $y (0 .. $to - 1) {
        my $sy = int($y * $from / $to);
        for my $x (0 .. $to - 1) {
            $out .= substr($buf, (($sy * $from) + int($x * $from / $to)) * 4, 4);
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

my ($pack_px, $pack_frames) = load_pack();
$PX = $pack_px if $pack_px;

open my $fh, '>', $tty or die "open $tty: $!\n";
select((select($fh), $| = 1)[0]);

# Keep clear of the right edge, scaled to the sprite: a cell is roughly 7px
# wide at any sane font size, so this stays a shade wider than the image and
# tucks into the corner without being clipped.
my $col = $cols - (int($PX / 7) + 1);
$col = 1 if $col < 1;
# Keyed on the window, not the pid, so a second alert replaces the sprite still
# sitting in that pane instead of stacking a new image on top of it.
my $id = 7000 + (($ENV{KITTY_WINDOW_ID} || $$) % 900);

# One pass of the animation. Returns roughly how long it took, so the persist
# loop below can bound itself without a clock.
sub play_once {
    my ($out) = @_;
    my $spent = 0;
    if ($pack_frames) {
        # Cap the run: some animations are 111 frames, which is a lot longer
        # than anyone wants an alert to sit on screen.
        my $n = @$pack_frames > 16 ? 16 : scalar @$pack_frames;
        for my $i (0 .. $n - 1) {
            send_frame($out, $pack_frames->[$i], $id, 1, $col);
            select(undef, undef, undef, $DELAY);
            $spent += $DELAY;
        }
    } else {
        send_frame($out, frame($_ / $FRAMES, 0), $id, 1, $col),
            select(undef, undef, undef, $DELAY), $spent += $DELAY
            for 1 .. $FRAMES;
        for (1 .. $PULSES) {
            send_frame($out, frame(1, 1), $id, 1, $col);
            select(undef, undef, undef, $DELAY * 1.6);
            send_frame($out, frame(1, 0), $id, 1, $col);
            select(undef, undef, undef, $DELAY * 1.6);
            $spent += $DELAY * 3.2;
        }
    }
    return $spent;
}

# Keep the animation running as an "I finished, you weren't here" marker and
# clear it when you come back. kitty has no keystroke event (see
# kitty-flash-watcher.py), so focus is the closest signal to "you typed in this
# pane". Skipped when the pane is already focused — you watched it happen.
# `kitty @ ls --match` still prints the whole OS-window/tab tree, so this walks
# to the window itself rather than pattern-matching the blob. JSON::PP is core.
#
# All three levels matter. A window keeps is_focused while it is merely the
# active window *of its tab*, so checking that alone reports "focused" for a
# pane sitting in a hidden tab, or in a kitty that isn't even the frontmost
# app — which is exactly when the sprite should still be running.
sub window_focused {
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

my $focused = window_focused();
my $persist = ($ENV{SPRITE_PERSIST} // 1) && defined($focused) && !$focused;

if ($persist) {
    close $fh;
    exit 0 if fork();                       # parent returns, sprite keeps going
    # Child: loop the animation until you arrive, then take it away. The focus
    # check costs a `kitty @ ls`, so it runs once per pass rather than per frame
    # — a pass is about a second, which is soon enough to feel instant.
    my $ttl = $ENV{SPRITE_TTL} || 1800;
    my $gap = $ENV{SPRITE_LOOP_GAP} // 0.6;
    my $waited = 0;
    open my $out, '>', $tty or exit 0;
    select((select($out), $| = 1)[0]);
    while ($waited < $ttl) {
        $waited += play_once($out);
        last if window_focused();
        select(undef, undef, undef, $gap);
        $waited += $gap;
    }
    print $out "\033_Ga=d,d=I,i=$id,q=2\033\\";
    close $out;
    exit 0;
}

play_once($fh);                              # focused pane: one pass and gone
print $fh "\033_Ga=d,d=I,i=$id,q=2\033\\";   # delete image + placements
close $fh;

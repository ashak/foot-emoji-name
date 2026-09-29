# foot-emoji-name

Press a hotkey in [foot] and every emoji on screen gets a label letter. Press a
letter and a desktop notification shows the emoji's name, codepoints and a big
coloured rendering.

Built for the Omarchy desktop. Two runtime dependencies come from Omarchy and
are env-overridable: the emoji database file and the notification tool.
Rendering the large emoji image additionally uses `pango-view`, `magick` and a
colour emoji font; if any of those is missing the toast still appears, just
without the image.

```
Ctrl+Shift+e      label every visible emoji (a-z)
<letter>          notify the name of that emoji
```

## How it works

Foot 1.14+ ships `regex-launch`: you give it a POSIX ERE pattern; on the hotkey
it labels every match in the viewport and on a keypress runs `launch` with the
matched text as `${match}`. This repo supplies the launcher plus a generator
that writes the whole foot config block (pattern, `launch=` and the hotkey
binding) into a file that your own foot.ini pulls in with one `include=` line:

- `foot-emoji-name` — the launcher. Looks the matched text up in an emoji
  database, renders a 200x200 PNG with `pango-view`+`magick` (cached under
  `$XDG_CACHE_HOME/foot-emoji-name/`), and shows the toast.
- `tools/generate.py` — generates the ini file foot includes: the `[regex:emoji]`
  section (`regex=` + `launch=`) and the `[key-bindings]` hotkey binding, with
  the pattern derived from the database. Writes it to foot's config directory.
- `tools/validate.py` — regression suite that compiles the pattern with the real
  glibc and asserts the invariants in both `C.UTF-8` and `en_GB.UTF-8`.

### The regex, and the traps that forced its shape

Foot compiles the pattern with glibc `regcomp(REG_EXTENDED)`:

- **Escapes are lies.** `\uXXXX`, `\xHH` and octal escapes are *not* handled by
  glibc's ERE. `[\uFE0F]` compiles, but it matches the literal ASCII characters
  `\`, `u`, `0`, `f`, `7`… rather than U+FE0F, so a pattern written that way
  matches plain ASCII text instead of emoji. The fix is real UTF-8 characters
  everywhere.
- **Ranges are locale-fragile.** A literal multibyte range like `[😀-🙏]`
  compiles under `en_GB.UTF-8` but fails with `REG_ECOLLATE` ("Invalid
  collation character") under `C.UTF-8`, which is what a foot started from a
  desktop launcher typically ends up in. Some ranges that do compile also
  match ASCII letters by collation quirk. The fix is no ranges at all.
- So the whole pattern is **pure UTF-8 literals with zero ranges** — identical
  behaviour in every UTF-8 locale. It matches one grapheme cluster at a time:

```
keycap      [0-9#*] <FE0F> <20E3>
flag        [regional][regional]                 (e.g. 🇬🇧)
subdivision <1F3F4> [tag letter]+ <E007F>         (e.g. 🏴󠁧󠁢󠁥󠁮󠁧󠁿)
cluster     R ([VS]|[SKIN])* (<ZWJ> R ([VS]|[SKIN])*)*
```

where `R` is a single character class holding every database character that is
not ASCII, not a regional indicator, not a skin tone, and not a ZWJ /
variation-selector / keycap-join continuation character.

The England/Scotland/Wales flags are a black flag plus tag letters plus a
cancel tag — all of them invisible formatting characters, since the flag is
drawn from the letters. They get their own alternative rather than being
swept into `R`, so that a whole flag matches as one span and a lone tag
character matches nothing at all.

## Install

1. Put the launcher on your `PATH` (it has no dependencies of its own):

   ```
   install -m755 foot-emoji-name ~/.local/bin/foot-emoji-name
   ```

2. Generate the ini file that foot includes. The pattern in it is derived from
   the emoji database; the whole block is written to
   `~/.config/foot/foot-emoji-regex.ini` (or
   `$XDG_CONFIG_HOME/foot/foot-emoji-regex.ini`):

   ```
   python3 tools/generate.py
   ```

   The file contains the `[regex:emoji]` section (`regex=` + `launch=`) and the
   `[key-bindings]` hotkey binding, so the main foot config only needs the one
   include line. The launch command and hotkey default to
   `~/.local/bin/foot-emoji-name` and `Control+Shift+e` (override with
   `--launch` / `--keybinding`). The command is idempotent: re-running it just
   rewrites the same byte-identical file.

3. Make sure `~/.config/foot/foot.ini` includes that file — that's the only
   line the feature needs:

   ```
   [main]
   include=~/.config/foot/foot-emoji-regex.ini
   ```

   The generated `[regex:emoji]` and `[key-bindings]` blocks are merged with
   whatever else your foot.ini defines (foot parses included files as part of
   the same config, section by section, key by key), so your own bindings and
   settings are untouched and the feature costs exactly this one line.

4. Check the config and relaunch foot:

   ```
   foot -C
   ```

   Then press `Ctrl+Shift+e` in a terminal with some emoji in it.

Note that foot refuses to start if an `include` target is missing, so if you
ever clear that file out, re-run `tools/generate.py` to recreate it.

## Regenerating

The ini file is derived from the emoji database, so re-run the generator whenever
that file changes. It rewrites `foot-emoji-regex.ini` in place; then re-check the
config and restart foot to pick it up:

```
python3 tools/generate.py
foot -C
```

With a database other than the Omarchy default, pass it explicitly:

```
python3 tools/generate.py --db /path/to/emojis.json
```

## Environment

- `FOOT_EMOJI_DB` — emoji database JSON (default
  `/usr/share/omarchy/shell/plugins/emojis/emojis.json`).
- `FOOT_EMOJI_NOTIFIER` — notification command (default
  `omarchy-notification-send`).
- `XDG_CACHE_HOME` — where rendered PNGs are cached (default `~/.cache`).

## Testing

```
python3 tools/validate.py                 # uses the omarchy default database
python3 tools/validate.py --pattern ~/.config/foot/foot-emoji-regex.ini
python3 tools/validate.py --db ../other.json
```

`--pattern` reads the `regex=` value out of a generated ini file (or a bare
pattern). The suite compiles it with glibc in `C.UTF-8` and `en_GB.UTF-8`,
asserts that every emoji in the database matches whole, that a corpus of
box-drawing, math, other scripts and typographic punctuation does *not* match,
that no ASCII character matches, that no character of the Unicode tag block
matches on its own, and that an empty match is impossible.

## Limitations

- Foot labels at most 26 matches (a-z) in the viewport.
- Without `pango-view`/`magick` (or a colour emoji font) the toast shows the
  name and codepoints only, with no rendered image.

[foot]: https://codeberg.org/dnkl/foot
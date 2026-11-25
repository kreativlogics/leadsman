# Vendored code

| File | Source | Upstream sha256 when copied | Changes |
|---|---|---|---|
| `plugins/leadsman/scripts/leadsman/secrets.py` | checkrein `plugins/checkrein/scripts/checkrein/secrets.py` (same author, MIT) | `ac97b456ebe244497e45d30df887b00ae9c176fd3e6b9a7eab6cd99606aed019` | See below |

Changes made in leadsman (so the file no longer matches upstream; the current sha256 is
`9deebe367c99fff9bc99be47f2ef24b434b9461c00d4bc7707ea0bfdd923322c`):

- Every pattern has an upper length bound, except the private-key block, whose open end takes the rest of the text
  in one match; so no pattern backtracks without limit.
- Assigned secrets are also found in backticks and without quotes (an unquoted value needs a letter, a digit and
  enough randomness).
- Lines are split on `\n` only, so line numbers match editors and git, and are scanned whole (no pattern backtracks
  without limit), so a secret far along a long line is still found.
- `found_values`, `remember` and `hide`: a secret found once is hidden wherever else it appears. Only values with 8+
  characters, a letter and a digit (or a known token format) are hidden everywhere, so ticket text cannot hide
  ordinary words.
- `mask` finds pattern matches and remembered values in the original text and hides them together, and the
  private-key pattern takes the whole BEGIN…END block, or the rest of the text when the END line is missing; `holds_private_key` is new.
- `found_values` also searches the whole text, so a value on the line after its name is found.
- `mask_tree` masks every string and key in a JSON value before it is printed; the JSON text itself is never masked.

Not vendored, written fresh for leadsman:

- `config.py` follows the same layered-config contract as checkrein (defaults, plugin option, user file, project file
  that can only tighten) but has its own keys and no rule levels, so none of checkrein's config code is copied.
- checkrein's approval store (`approve.py`) is not needed: leadsman has no settings that run programs.

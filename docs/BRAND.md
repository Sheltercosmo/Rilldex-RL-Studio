# Rilldex — RL Behavior Inspector

**Rilldex** is pronounced **RILL-deks**. The name joins *rill*, a small stream,
with the idea of an *index*: streams of rollout evidence made inspectable.
Use **Rilldex — RL Behavior Inspector** as the full name in introductions,
package descriptions, documentation and the logo lockup. **Rilldex** is the short
name in navigation, conversation and commands. This pairs a searchable name
with an immediate explanation of the product. The short line is
**Make RL behavior inspectable.**

## Identity

- Product: **Rilldex**. Wordmark: **Rilldex**.
- Distribution, command and module entry point: `rilldex`.
- SDK: existing `tracker` imports stay stable; no training code changes required.
- [SVG mark](../tracker/web/rilldex-mark.svg) and
  [SVG logo](../tracker/web/rilldex-logo.svg).
- The mark is a branching path forming an R. A mint branch distinguishes the
  alternate path; shape, rather than color alone, identifies the mark.
- Ink `#19212f`, white `#ffffff`, mint `#75e2ca`. Keep clear space around the
  symbol. In navigation use a 32 px mark; the SVG also serves as the favicon.
  Interface colors continue to encode activities, relationships and status.

## Interface surfaces

The UI retains its original cobalt interaction color (`#3659e3`), white panels
and ink (`#19212f`). The large canvas is only slightly more neutral (`#f7f8fa`);
blue belongs mainly to selection, links and focus. Shared tokens live in
`workspace.css`. Secondary text is `#5e697b`; avoid pale text on tinted backgrounds.
Controls and cards are flat, with quiet borders and no bevels or gradient fills.
Reserve shadows for floating menus and dialogs. Preserve visible focus rings.

Geist Sans and Geist Mono 1.7.2 are bundled locally under the SIL Open Font
License (see `tracker/web/geist-LICENSE.txt`), so offline deployments need no
font CDN. Code uses 13 px Mono with preserved whitespace and horizontal scrolling;
never break commands in the middle of a token. The local Prism 1.30.0 core,
Python and Bash grammars add restrained syntax color (MIT license in
`tracker/web/prism-LICENSE.txt`). Rendering checks text equality, including whitespace,
and follows regenerated snippets without changing their copy behavior. Native select controls retain form
semantics and keyboard behavior. Supporting desktop browsers get styled, bounded
pickers with wrapping options; touch and other browsers retain OS pickers.

The refinement draws on [Linear's March 2026 refresh](https://linear.app/now/behind-the-latest-design-refresh)
(quieter surfaces and consistent hierarchy), and Geist's
[typography](https://vercel.com/geist/typography) and
[code block](https://vercel.com/geist/code-block) guidance. These inform details,
not a replacement identity. Native picker enhancement follows
[Chrome's customizable select implementation](https://developer.chrome.com/blog/a-customizable-select).

Map kinds use slate for source records, indigo for contributions, teal for actions,
and amber for returned feedback. Symbols and labels accompany these colors.
Relations keep their own arrow labels and dash patterns; status colors do not
replace evidence wording. All map levels open in the normal workspace. Expanded
canvas mode is an explicit user choice, not a default of the unit map.

## Name screening, 15 October 2026

Exact-name general/software searches found no Rilldex product. The GitHub
repository-name API returned zero matches. PyPI and npm exact-name endpoints
returned 404. This is a public collision screen, not a name reservation or a
trademark clearance; no package, domain or account was registered.

The checks are reproducible at
`https://api.github.com/search/repositories?q=rilldex+in%3Aname`,
`https://pypi.org/pypi/rilldex/json` and
`https://registry.npmjs.org/rilldex`.

Rejected candidates included Orvyn (AI engineering products), Rovyn (active AI
apps), Rolviz (near-identical Rollviz repository), Runweft (agent testing tool),
Runlith (AI coding product), and Rollume (existing consumer website). Search
results for the near spelling Rildex concerned unrelated consumer products;
use the exact spelling Rilldex consistently. Rilldex has no affiliation with
Rill Data or other analytics products.

## Upgrade an existing installation

Stop the collector, keep the database, outboxes and configuration files, then
run these commands **in its existing Python environment**, from this checkout:

```sh
python -m pip uninstall jev-rl-tracker
python -m pip install .
rilldex --version
rilldex --db /path/to/existing/workspace.sqlite start
```

Remove the old distribution **before** installing the new one: they share the
stable `tracker` Python package. Uninstalling the old distribution afterwards
could remove shared files. No user database is part of the wheel.
For a fresh environment, just `python -m pip install .`.

`python -m rilldex` works when the executable directory is not on PATH.
`jev-track` and `python -m tracker` remain compatibility entry points.
They use the same implementation and default `.tracker/tracker.sqlite` path.
No re-import, annotation or model recalculation is needed.

New launch files use `rilldex-launch/1` and `job.rilldex.json`. Old
`jev-launch/1` files remain accepted with identical path and producer semantics.
Workspace/capture archive filenames use `.rilldex.zip` / `.rilldex-capture.zip`;
older filenames remain valid because readers inspect the archive contents.
Versioned data protocols, content hashes, provider names, browser history keys
and `.jev-capture-locks` retain their original identities for compatibility.
Jev is still the name of the Typesafe selection provider, and `JEV_API_KEY`
still configures that provider; it is no longer the product name.

Compose now accepts `RILLDEX_PORT`, `RILLDEX_OUTPUT_DIR`, `RILLDEX_INPUT_MODE`,
`RILLDEX_EXPERIMENT` and `RILLDEX_PRODUCER`. Each falls back to its former
`JEV_` variable. Its existing service and `jev-data` volume key are deliberately
retained: update in the same Compose project/directory to keep the same storage.
Fresh standalone Docker setup instructions use `rilldex` / `rilldex-data`.
Existing standalone installations must retain their original mounted volume.

For systemd, use [rilldex.service](../deploy/rilldex.service). When upgrading,
stop and disable the old service before enabling the new one; keep the same
database path. Do not run both services on one workspace.

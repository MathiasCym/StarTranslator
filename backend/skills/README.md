# Bundled document skills

星译官 uses a task-specific adaptation of Humanizer and OfficeCLI for technical
translation and proofreading. `translation-rules.md` is loaded into both model
tasks. The original pinned skill documents and upstream licenses are retained
in their respective folders; provenance is recorded in `sources.json`.

Humanizer's prose rules are adapted to preserve technical meaning, terminology,
numbers and model codes. The application returns its existing JSON contracts,
not Humanizer's interactive draft/audit format. Writing preferences do not turn
valid synonyms or acceptable English into proofreading errors.

OfficeCLI is bundled as an unmodified, self-contained Windows x64 executable
in `resources/officecli` (development: `vendor/officecli`). The application runs
fixed, read-only validation and format-inspection commands before and after PPT
changes. It does not execute document instructions or model-generated commands.
No additional account, installer, runtime download or Office installation is
required for these checks. Automatic resident mode is disabled.

PPT changes are written to the original Office package: only changed slide/notes
parts are replaced. Other package parts are copied unchanged. Translation keeps
style IDs aligned with their meanings; proofreading changes only selected spans.
Existing templates, geometry, inline styles and relationships take priority.
New structure errors block export; new estimated overflow is shown to the user.
The checks are not a full PowerPoint rendering guarantee. Images, charts and
unsupported complex text are reported for manual handling.

Upstream distributions and licenses:

- Humanizer: https://github.com/blader/humanizer — MIT.
- OfficeCLI: https://github.com/iOfficeAI/OfficeCLI — Apache-2.0; NOTICE retained.

The adaptation and application bridge are maintained by StarTranslator.

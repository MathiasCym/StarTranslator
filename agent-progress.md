# Reverse translation quality repair and delivery

## 2026-10-26 — baseline and user direction

- Status: in progress. User explicitly requires repeated testing and modification until the reproduced problems are resolved, then one next-version update.
- Baseline: clean main `6e382953bdcb9a5eb4c8fda57f952ea15fb17460`, released product `f919c160ff82d15017a109b5bcf35f9748eb89d9`, version 2.2.6. Do not replace published 2.2.6 bytes.
- Evidence: ignored `dist/qa/en-zh-effect-20261026/`. All test inputs synthetic; actual company model and extracted official backend/runtime used. 13 document extensions (11 families), 93 translatable blocks, free text 5 blocks, 322 model method calls. Failed real results and native snapshots retained unchanged.
- Confirmed: PDF units/extraction and model false rejection retain whole English blocks; HTML inline segmentation duplicates negation; Chinese review refuses safely locatable substring proposals; saved reverse files lose pending counters; review checkpoints contain transient draft paths; first-use glossary initialization races; red/bold negation emphasis expands beyond the corresponding phrase.
- Native Word 2 pages, PDF-derived Word 2 pages, PPT 3 pages inspected. Excel text, formulas, numeric cells, links, merges and styles pass; native local spreadsheet PDF export clips both source and output, so that renderer cannot prove translation-specific layout quality.
- No product code or version changed yet. Skills: effective-harnesses is used for this durable checklist. Next: feat-001 and its regression tests, then remaining features sequentially.
- Network: preserve existing proxy/model settings, use configured intranet client only for synthetic test content, no credentials printed. All work through background tools; no web clicking.

## 2026-10-26 — implementation and first repeated validation

- Implemented pending-save status/audit, uniquely locatable Chinese review suggestions with bounded repair, stable review checkpoints, safe PDF whitespace-only recovery and physical-wrap merging, generated PDF label localization, reverse-only inline semantic units preserving raw tags/keys/targets, startup migration serialization, and semantic emphasis verification/repair without retranslating accepted content.
- Targeted results: reverse translation 13 tests, text translation 12, PDF reflow 20, glossary bundled 15, original generic formats 18 passed. Added tests first failed on released behavior.
- First PDF repair changed 2/4 to 4/4 translated, but physical-fold duplication still failed independent audit; fixed by unconditionally merging PDF physical wraps after whitespace verification. Do not count that intermediate run as accepted.
- Running: source-round1 real company-model 13-extension matrix (process session 97966), full canonical regressions with cached xlsxwriter test dependency (session 27169). Logs under dist/qa/en-zh-effect-20261026/. No version change, source commit or release yet.
- The baseline error-path and checkpoint scripts target extracted 2.2.6; for source acceptance they must switch sys.path to current checkout and use fresh profiles for initial runs, same profile for recovery. Existing official installer/payload must remain unchanged.

## 2026-10-26 — repeated real-model repairs and current gate

- Full source backend regression passed 564 tests before the final additional regressions. Current targeted reverse suite is 15 tests and free-text suite 13; expected full count now 567.
- Added document-scoped person recognition with exact spelling/confirmed glossary mapping, validation in translation and Chinese review, and checkpoint reuse. Free text uses the same ephemeral policy without creating files.
- Solved style repair by immutable exact anchors; isolated negation emphasis cannot include timing/condition clauses even when model claims it is correct. Fixed inline tags can trigger a bounded, fact-rechecked Chinese word-order adjustment.
- Corrected reverse bit/位/比特 equivalence without treating people counters as bits; ordinary unit and number protections remain. Reviewer-provided full corrections are independently revalidated, and brand/ambiguous glossary/valid unit variants no longer incorrectly force a whole English fallback. Snapshot translation count before visual fit because that stage can append changed locators.
- source-round5: Word 21/21, PPT 12/12, PDF 4/4, HTML 6/6 all actual model, Chinese review, save, structural checks, independent bilingual audit PASS; no cached translation, no pending source. Strict negation color/bold scopes passed. inline-round4 HTML+HTM separately passed. PDF also passed source-round2 and source-round3. Intermediate failures remain recorded, do not overwrite them.
- Running final 13-extension actual matrix: session 92370, source-final.log; running canonical final regressions: session 64734, final-regressions.log. No version increment/commit/release yet. One HTM independent QA audit falsely required each inline fragment to be a full sentence; actual combined visible text is correct. Updated QA audit to use logical joined text and forbid grammar-style false positives; re-audit that existing actual file rather than altering output.
- tools/check-document-quality.py now supports --direction en-zh while default remains zh-en. Needs actual source fresh + --resume --forbid-requests validation. Isolated QA scripts originally hardcode released 2.2.6; switch paths for current source recovery/error tests. PPT native image review deliberately remains separate and may request fresh model vision; prove no-request text/review reuse on other formats and do not claim all PPT rendering is cached.
- Outstanding: final matrix results and independent HTM re-audit; source error/recovery probes; fresh repeated critical cases if any confirmed failures; native final Word/PDF/PPT page inspection; final full/maintenance/UI checks; choose 2.2.7 patch once; update docs/changelog/version and fixed release workflow; CI originals + domestic original patches and actual old-client upgrade. Never change installed app or existing 2.2.6 release.

## 2026-10-26 — final paragraph refinement and frozen acceptance

- Critical four-format source-round5 all passed; initial full 13-extension source-final effective all passed after a correctly joined HTM independent re-audit (actual file unchanged). Word/PPT native snapshots show correct isolated red 请勿 and no clipping. 12-extension no-request translation + Chinese-review recovery passed, source saved-partial counters passed, free text both directions passed.
- Native inspection then caught dense PDF paragraphs caused by merging all physical folds. Added whitespace-only logical paragraph normalization, conservative merging of lowercase sentence tails, and tests. Actual pdf-paragraph-proof passed, native 2-page output inspected and is readable with separate logical lines. This refinement changed reverse policy, so earlier checkpoint profiles intentionally no longer match; do not claim a subsequent forbidden-resume against that old policy is a failure of unchanged-code recovery.
- Person detection now accepts real-name substrings of a joined candidate and treats whitespace-wrapped names as one identity. Current targeted reverse tests: 17 pass, text tests: 13 pass. Expected total 569. No further backend changes planned.
- Running frozen all-format rerun source-final2: session 1767, source-final2.log. Running frozen full regressions: session 62419, frozen-regressions.log. Installation/update maintenance 116 passed (session 26877).
- Public CLI first fresh direction en-zh proof passed (12 model requests), but its subsequent resume ran AFTER the PDF/name policy edit and correctly blocked 4 new requests. Create a NEW public-cli-final profile, then immediately run --resume --forbid-requests with unchanged code for the actual final acceptance.
- QA tooling note: free_text_final.py initially logged calls to source-final/calls-private.json, replacing the matrix call trace. All per-format job/save/result and real output/native evidence remain intact. Fixed future free-text logs to a separate child folder. Do not quote a total model-call count from source-final/calls-private.json. Other round traces retained.
- Outstanding: current frozen matrix/full results; new final recovery and CLI fresh+resume; final native snapshots with logical PDF; UI checks; prepare single 2.2.7 version and docs; commit/push exact tree; formal CI, original installer saved in dist, domestic last-three original small patches, real isolated old 2.2.6 upgrade; final evidence/docs.

## 2026-10-27 — source gates complete, formal delivery next

- Frozen policy final release-final: all 13 translations/reviews/saves complete; 12 independent semantic audits pass directly. PDF audit false-with-no-issue was retained, reread actual text, then release-pdf-repeat fresh 4/4 passed all checks in 73 seconds. No output was fixed by QA. Native final Word 2, PDF 2, PPT 3 pages inspected, original/output fingerprints unchanged by rendering.
- Fixed the last reproduced PDF numeric fact view (is2.5/to40, preserving actual codes) and saved reverse history quality resolution, with targeted regressions. Full final backend: 569 pass.
- 12-extension text/review recovery zero model attempts; public quality tool en-zh fresh 12 requests then immediate forbidden-resume sent=blocked=0; free text both directions passes. PPT image work may re-request; do not claim zero-request PPT visual cache.
- UI/readability/fullscreen/real default and four display scenarios pass. Fixed test fixture zoom after destroying the app window to prevent same-origin zoom bleed; no product scale change. 116 maintenance and 1 actual small updater restart test pass.
- Prepared version 2.2.7 once, date 2026-10-27, docs/changelog and ignored formal-2-2-7-20261026 delivery scripts. Pending: one source commit/API exact-tree publication, CI originals, domestic original patches for 2.2.4/.5/.6, actual isolated old 2.2.6 update, payload/runtime checks and final record/docs-only commit. Real install and profile remain untouched.

## 2026-10-27 — completed 2.2.7 delivery

- Product commit e67fa83291a8a5eadedd673b7689dcd399398beb, tree 964bbc50041afd2af1f8d2212dcce055ca26f8db. GitHub API exact-tree fallback matched local Git; canonical commit aligned, original local commit archived.
- CI 40432410416 and public-mirror job successful. Original installer dist/StarTranslator-Setup-2.2.7.exe: 144311902 bytes, SHA-256 0a0528dc01b13568eee228903f268e62a59c100594b2117dd0a0987109a5f125. Fresh extraction 1296 checked, recovery/new backend/source matching, 105 packaged tests, setup images and actual default window passed.
- Domestic formal original deltas 2.2.4/.5/.6 anonymously downloaded over direct session with no GitHub; same bytes/digests as original release. Actual old 2.2.6 component downloaded/applied 1481539-byte delta; final manifest matched, personal fixture and glossary preserved, owned update cache cleaned. Upgraded real app 2.2.7 and actual glossary 2515 with personal notes/aliases passed. Real installation untouched.
- No unresolved delivery items. PDF bitmap/original layout, spreadsheet native exporter limitations, and PPT visual re-request boundaries remain explicitly documented. Final step is docs-only commit/mirror of this completed record; no product rebuild or version change.

## 2026-10-29 — 2.3 numbering and confirmed LAN entry discovery

- User approved 2.2.6 -> 2.3.0, 2.2.7 -> 2.3.1 historical display. Metadata commit 58bb383d01c802d745e8929eff996af5a31bbb3f, mirror 40819661000 and relabel 40819661036 succeeded. Four public release pages read back, original assets and identities unchanged. Real old installer versions/tags stay 2.2.6/2.2.7.
- Initially no API failure reproduced: source, installed 2.2.7 backend, real private HTTP address and selected real model completed both directions with synthetic text. User then clarified: could not find the text entry. Do not claim a translation backend defect.
- Confirmed UI fix: text button moved into top of new-task card, existing primary styling, explicit no-upload description. No backend, model, proxy, global size or real installation changes. Source UI/readability passed including 360/480/900/1280 first-screen visibility and hit-testing; actual Flask shared service from the new entry completed both directions. 116 maintenance tests pass.
- Product version chosen ONCE: 2.3.2. Source commit f143f36d62de91dff3766f77701b5399342d3a4d, tree 35a52e327c4f819c63fcdd54bb658e1879657b02. CI 40826921607 running, initial source mirror 40826921547 succeeded. Local/remote exact Git trees matched and canonical commit aligned.
- Active bounded watch: exec session 49785, logs dist/qa/formal-2-3-2-20261029/ci-watch.log. It waits on run 40826921607, downloads original GitHub installer to dist and extracts fresh payload. Do not run a local rebuild or increment again.
- Remaining delivery: CI formal full/patch assets; postbuild.ps1 in same folder; original domestic last-three baselines 2.2.5/2.2.6/2.2.7; actual isolated 2.2.7 upgrade via verify-domestic-upgrade.cjs, then verify-applied.cjs and check-upgraded-app.cjs; actual packaged LAN page using private service.py backend argument. Update docs/validation-2.3.2.md/next-release and root tracking only after actual success, docs-only commit/mirror, clean Git.
- Prepared QA old profile with 2515 terms and personal note/alias. Test helpers all under ignored formal-2-3-2-20261029. source-commit.txt stays product f143... even after later docs-only head. Original baseline payload at formal-2-2-7-20261026/payload. Real installed app and profile untouched.

## 2026-10-29 — completed 2.3.2 product delivery

- CI 40826921607 Windows and domestic mirror successful, 569 backend/116 maintenance/1 native updater restart, 105 packaged checks pass. Original dist/StarTranslator-Setup-2.3.2.exe: 144314013 bytes, SHA-256 6556324fcc197c3168bfd117b9d7e3c94a6f4a5365875b247f4d0b4ac599b53e. Fresh extraction 1296 files matches source/stage/recovery; setup images and actual main window passed.
- Actual packaged Python/backend/shared HTML from the new task-card entry completed both directions with isolated fixture model; actual compiled shared home inspected. Backend and update libraries unchanged from original 2.2.7.
- All three original domestic deltas 2.2.5/.6/.7 anonymously read directly and matched GitHub. Original 2.2.7 updater downloaded/applied 1273734 bytes to isolated copy; 1296-file manifest exact, personal fixture and glossary retained, update cache removed. Actual upgraded app 2.3.2 launched, glossary 2515 with personal note/alias intact. Real install and model/proxy settings untouched.
- No pending delivery items. Final step: commit/mirror completed docs and tracking only, no rebuild/version increment. Product source remains f143f36d62de91dff3766f77701b5399342d3a4d; formal evidence under dist/qa/formal-2-3-2-20261029.


## 2026-10-31 — 2.3.3 implementation verified, formal delivery pending

- User requested removal of visible legacy directory branding, all 8 official glossary languages for reference only, no saved model profile limit and LAN scrollbar repair. All-language public term publication explicitly authorized; original XLSX stays private.
- Source tests: 573 backend, 122 maintenance and actual small-updater restart passed; catalog all source cells exact, 1965 rows, bilingual 2515 unchanged. 6 directory migration tests and actual main/Python startup pass with original encrypted bytes and old references. UI 8-language searches, paging, focus and narrow layout pass. LAN multiple addresses folded, common display checks running.
- Version selected ONCE: 2.3.3. Do not bump again. Remaining: full CI original installer, fresh payload checks, domestic deltas from actual recent 2.2.6/2.2.7/2.3.2, isolated old-client apply, package migration/new catalog, final records and docs-only sync. No real user data modified.


## 2026-10-31 — completed 2.3.3 delivery

- Product source 6fe1eccecb08332ec00b4ad85f4aa11e2d50ad12, CI 41188876137 Windows/domestic success. Original installer 144448178 bytes, SHA-256 0bbcb6eb69bea93faa09ea69cd6d5a2e2c8845391f5bb30533d5ae120ecef99d. 1298 fresh payload files and recovery copies exact; 125 packaged tests, setup images, actual default window and package migration passed.
- Source: 573 backend, 122 maintenance, actual updater restart, all original glossary language cells exact, actual profile migration and checkpoint/history database reuse, common display matrices passed.
- Domestic original 2.2.6/2.2.7/2.3.2 deltas anonymous direct read match GitHub. Actual original 2.3.2 updater applied 1585559 bytes, full target manifest exact, personal data retained and cache cleaned. Actual upgraded 2.3.3 opened, 2515 bilingual and 1965 multilingual/8 language searches passed. Real user profile/installation, model/proxy and source workbook untouched.
- No required product work remains; commit/mirror final docs and tracking only, no rebuild or version bump. Evidence dist/qa/formal-2-3-3-20261031.


## 2.3.4 — empty profile placeholder and truthful multilingual reference, release pending

- Reproduced real installed 2.3.3 in isolation: existing empty StarTranslator directory caused legacy fallback. Actual source catalog and current read-only HTTP response contain all source values; default selected source row has six genuinely missing language cells. Preserve these gaps, never fabricate translations.
- 9 directory tests, 4 backend catalog tests, actual main/Python migration with empty target and 8-language UI default/filter/search/missing-source checks passed. User data untouched; company models not called.
- One version selected: 2.3.4. CI original installer, domestic original deltas and actual isolated old-client upgrade still required.

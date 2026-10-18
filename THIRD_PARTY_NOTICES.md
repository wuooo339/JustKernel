# Third-party notices

The MIT license at the repository root covers original JustKernel code and documentation. It does not grant rights to third-party software, competition materials, model services, or CANN binaries.

- **xterm.js 6.0.0**: the vendored browser terminal is MIT licensed. Its original notice and full license are preserved in `src/aworker/lab/resources/web/vendor/NOTICE.txt` and `xterm-LICENSE`.
- **Python dependencies**: Deep Agents, LangGraph, LangChain, the A2A SDK and other packages retain their upstream licenses. Dependencies are resolved through `pyproject.toml` / `uv.lock`, not copied into this repository.
- **CANN Judge ConfusionMulGrad template**: the original contest archive did not contain a license notice. Its 34 source files are therefore **not redistributed** in Git, wheels, source distributions, or source ZIPs. `tools/import_official_template.py` downloads from the official endpoint (or imports a ZIP you obtained yourself) and validates each file against pinned SHA256 hashes. Obtain and use it under the contest platform's terms. Public metadata identifies the problem and editable paths; local cases are our provisional test definitions, not hidden official inputs. The historical archive hash in `input-source.json` records provenance; ZIP container metadata can vary, so the importer checks file contents individually.
- **CANN Toolkit, ops packages and simulator**: obtained and installed separately from Huawei, subject to their own agreements. No installer, compiler, driver, simulator library or other CANN binary is distributed here.
- **Historical optimized RotaryPosEmb baseline**: retained only in the maintainer's private workspace, excluded from public artifacts. Compatibility code and metadata remain for old journals; the public fallback explicitly fails if executed and is not an optimized kernel example.
- **README animation**: original JustKernel illustrative artwork, generated from scripted geometry and mock activity. It contains no third-party video frames, official results or private execution records.

Product names and trademarks belong to their respective owners. JustKernel is an independent research project and does not imply endorsement by Huawei, OpenAI, DeepSeek or the contest organizers.

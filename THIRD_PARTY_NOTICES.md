# Third-party Notices and License Scope

The root [MIT License](LICENSE) applies to original AlphaForge source code and
documentation authored by the AlphaForge Team. It does not replace, override,
or grant additional rights under any third-party license, subscription,
contract, publisher policy, or terms of service.

## QuantConnect LEAN

The LEAN Worker Docker build downloads and builds QuantConnect LEAN from its
upstream public repository. QuantConnect LEAN is licensed separately under the
Apache License 2.0. The AlphaForge MIT License does not relicense LEAN.

Review the upstream project and license before distributing a derived image:

- <https://github.com/QuantConnect/Lean>
- <https://github.com/QuantConnect/Lean/blob/master/LICENSE>

The pinned upstream commit used by the current Docker build is configured by
`LEAN_REF` in `compose.yaml`.

## Software Dependencies and Container Images

AlphaForge uses third-party packages and container images, including React,
Vite, Recharts, FastAPI, Pydantic, Uvicorn, NumPy, pandas, SciPy,
scikit-learn, Requests, Microsoft .NET, Python, and Miniconda/conda-forge
components. Each component remains governed by its own license and notice
requirements.

Dependency declarations are available in:

- `frontend/package.json`
- `backend/requirements.txt`
- `lean_worker/requirements.lock.txt`
- `lean_worker/Dockerfile`

Redistribution of built images may require preserving the applicable licenses,
copyright notices, and attribution files for the included components.

## Market Data and Tiingo

No downloaded Tiingo market data is licensed under the AlphaForge MIT License.
The project follows a bring-your-own-token model. API access, downloaded data,
derived displays, hosting, and redistribution remain subject to Tiingo's
current terms and the user's subscription agreement.

Real market data under `lean_worker/workspace/data/` is intentionally excluded
from Git. Do not publish or redistribute downloaded data unless the account
holder has the required permission or redistribution license.

See `lean_worker/docs/DATA_SOURCE_AND_LICENSE_zh.md` for the project's data,
adjustment, attribution, and known Security Master limitations.

## Academic Papers and Publisher Material

PDF papers under `docs/research/papers/` are copyright their respective
authors and publishers. They are not covered by the AlphaForge MIT License,
and their presence in a local or course repository does not grant public
redistribution rights.

Before making this repository public, the maintainers must verify that every
tracked PDF may be redistributed. If permission cannot be confirmed, remove
the PDF from the public Git history and retain only bibliographic metadata,
citations, DOI links, or publisher-authorized open-access links.

## External Services and Trademarks

DeepSeek and any other OpenAI-compatible model provider are external services
subject to their own terms. QuantConnect, LEAN, Tiingo, DeepSeek, Microsoft,
Python, React, and other names may be trademarks of their respective owners.
Their use in this project is descriptive and does not imply endorsement.

## Additional Worker Notice

Worker-specific notices are retained in:

- `lean_worker/LICENSE`
- `lean_worker/THIRD_PARTY_NOTICES.md`


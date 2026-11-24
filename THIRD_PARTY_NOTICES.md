# Third-Party Notices

This repository contains an independently written Python implementation of the
DuMate login-bonus flow. Account credentials are supplied at runtime and are
not included in the repository.

## Protocol Evidence

### magpie-dumate

- Source: `R227BOUT/magpie-dumate`
- Fixed commit reviewed: `1d950b324b971fa162183d8114ce38a9ea411559`
- License: MIT
- Use: request paths, response-field semantics, cookie handling, and check-in
  success criteria were reviewed as protocol evidence.
- Local implementation: Python, requests-based, independently structured, with
  an additional cookie-file workflow and a stricter positive-points-delta gate.

The upstream MIT notice is reproduced below:

```text
MIT License

Copyright (c) 2026 magpie-plugin-dumate contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Runtime Dependencies

- `requests` is installed from PyPI under its own license.
- `cryptography` is installed from PyPI under its own license and is used only
  by the optional desktop-session import helper.

## Project License

The local implementation is released under the MIT License reproduced in
[`LICENSE`](LICENSE).

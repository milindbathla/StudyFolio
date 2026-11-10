# Reference attribution

The design review used commit `c1b36df38b8cb1e737f5f298de7aaeda2aab94be` of the J.A.R.V.I.S. reference repository. Its source was inspected in a temporary checkout outside this project. Studyfolio's implementation was written independently. [Reference repository at the reviewed revision](https://github.com/aditikm24/local_system_automation/tree/c1b36df38b8cb1e737f5f298de7aaeda2aab94be)

| Reference file | Reviewed concept | Studyfolio implementation |
| --- | --- | --- |
| `short_term_memory.py` | Timestamped roles, age/count pruning, restore and recent-context formatting | A bounded session-specific SQLite view over durable raw messages |
| `user_persona.py` | Incremental profile patches, list additions/removals, selective updates and stale preferences | Validated field proposals, evidence links, human decisions and revision records |
| `persona_rag.py` | Core identity versus selectively retrieved supplemental details | Field-level persona assertions and query-specific ranked context |
| `RAG.py` | Chunk selection, local embedding and nearest-neighbor retrieval | Persistent Chroma collections over atomic facts and segmented episodes, plus SQLite FTS5 |
| `live_audio.py` | Memory context injection and reflection on standby or scheduled checks | Message thresholds, close/manual/hourly triggers, and persisted recovery jobs |

The reference copyright and permission notice is reproduced below. [Upstream MIT license](https://github.com/aditikm24/local_system_automation/blob/c1b36df38b8cb1e737f5f298de7aaeda2aab94be/LICENSE)

```text
MIT License

Copyright (c) 2026 Vishesh Kumar Singh

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

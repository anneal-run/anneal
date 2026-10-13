# BUILD_LOG: github_triage baseline

- Start: Tue Oct 13 17:47:12 IDT 2026
- End: Tue Oct 13 17:51:09 IDT 2026
- Time spent: 3 min 57 s (wall clock, one sitting, including reading the traces, writing code, tests and this log)

## What I built

`workflow.py`, `run(repo, number, tools, model)`:

1. `get_issue` and `list_labels`. Labels whose description says they are for pull requests
   (and does not mention issues) are dropped from the menu (`build:*`, `test:*` and the like).
2. Candidate search, deterministic. GitHub search ANDs terms; in the traces 115 of 263
   agent searches returned nothing because the queries were 5-8 words long. So I build
   short queries from the title: strip template prefixes (`[BUG]`, `Bug:`, `Feature request:`),
   drop stopwords, version strings, the owner and repo name, redaction placeholders; score
   tokens (identifiers with `_ - . /`, code spans and ALLCAPS score higher); take the top 4,
   then the top 2, then the top 3 of the first error/panic line in the body. At most 3
   searches, stop early at 6 candidates, keep up to 10.
3. One model call (structured): labels, `duplicate_of` (0 = none), a confidence, the reply.
   Input is the label list with descriptions, the candidate titles, and the issue body with
   HTML comments and images removed, cut at 4000 characters. About 1.7k input tokens on the
   recorded issues, against ~23k summed over the agent's 5-6 calls.
4. Only when the model proposes a duplicate with `high` confidence and the number is one of
   the searched candidates: fetch that issue and ask a second model call whether it is the
   same problem. If not, the duplicate is dropped and that call's replacement reply is used.
   If the fetch fails, the high-confidence title match is kept.
5. Validation: labels are mapped case-insensitively onto the repo's names, unknown ones
   dropped; the repo's `duplicate` label is added for a confirmed duplicate and removed
   otherwise. If no valid label survives, retry once with the exact list; then raise.
   Bad repo string, missing issue (ToolError), repo with no labels, empty reply: raise.

Model calls per issue: 1, or 2 when a duplicate is proposed (4 of 140 traces), plus at most
one retry on an unparseable answer or an all-invalid label set.

## What I needed and where it came from

- Task, tool and model contracts: BRIEF.md, interface.py.
- Pass condition and its limits: RUBRIC.md.
- Label set, issue template shape (`### Summary / Platform / Version`), body length
  distribution, the agent's label frequencies (bug 84/140, area:* most of the rest), its
  duplicate rate (4/140) and its search behaviour (zero-result long queries): traces.jsonl,
  read with small python snippets.
- Nothing else. No ground truth labels were available, so I could not measure label accuracy
  offline; the tests check the plumbing, validation and failure behaviour, and a replay
  over all 140 recorded tool results checks that every recorded issue runs end to end.

## Assumptions

- `model.complete` with a schema returns a dict; I used `integer` with 0 for "no duplicate"
  rather than a nullable type, in case the structured-output layer does not support unions.
- `search_similar_issues` already restricts to earlier issues, as the brief says. I still
  exclude the issue's own number.
- Tool cost is not counted, only model tokens; so I spend up to 3 searches to save tokens.
- A duplicate must be among the searched candidates; the model is not trusted to remember
  issue numbers.
- When the earlier issue cannot be fetched, I keep a high-confidence title-level duplicate
  rather than drop it. This could be the wrong call; it is one line to change.
- `interface.py` may not be importable when the harness loads `workflow.py` by path, so
  the import has a fallback, and the confirmation fetch catches any exception (the harness's
  ToolError may be a different class object).

## Behaviour on other repositories, templates and topics

- Nothing is specific to astral-sh/uv: no label names are hard-coded except recognising a
  `duplicate` label by name; the label menu, descriptions and candidates come from the tools.
- Template prefixes are stripped generically; HTML template comments are removed.
- Repos with hundreds of labels make the prompt bigger (one line per label); repos with no
  labels raise. Repos whose labels have no descriptions rely on the names alone.
- Non-English titles: the tokenizer is ASCII-only, so search queries may be weak or fall
  back to raw words; the model call still sees the full text.

## Questions for the maintainers

1. Are template/bot labels (e.g. one applied on creation) wanted in the suggestions, or
   only judgment labels? The rubric rewards them; a real triager might not.
2. Should a duplicate of a closed issue be marked, or only of an open one?
3. Should we suggest `needs-mre`-style "needs info" labels when the report lacks a repro?
4. Is it acceptable to keep a title-level duplicate when the earlier issue cannot be read?
5. Is there a label budget (max labels per issue)?

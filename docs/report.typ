// Canonical editable course report. Compile from this directory with:
// typst compile report.typ report.pdf
#import "layout.typ": template

#show: template.with(
  author: "Marcus Gustafsson",
  date: datetime(year: 2026, month: 10, day: 19),
  course: "SWCON2627 — Software Construction",
  assignment: "ResearchPilot and ResearchPilot-SDD — Course project report",
)
#set document(
  title: "An Experience Report on a Specification-Driven, AI-Assisted Software Construction Project",
  author: "Marcus Gustafsson",
  date: datetime(year: 2026, month: 10, day: 19),
)
#set text(lang: "en")
#set par(leading: 0.55em)
#show heading: set block(above: 1.15em, below: 0.55em)
#set list(spacing: 0.35em)
#set enum(spacing: 0.35em)
#set table.cell(breakable: false)

#let report-table(columns: auto, ..cells) = {
  set text(size: 10pt)
  table(
    columns: columns,
    inset: 5pt,
    stroke: 0.45pt + luma(72%),
    fill: (x, y) => if y == 0 { luma(92%) } else { none },
    align: left + top,
    ..cells.pos(),
  )
}

#align(center)[#text(
  size: 17pt,
  weight: "bold",
)[An Experience Report on a Specification-Driven, AI-Assisted Software Construction Project]]

#heading(level: 1, numbering: none)[Team Details (Team — ResearchPilot / ResearchPilot-SDD)]

#report-table(
  columns: (1.15fr, 1fr, 2.4fr, 0.8fr),
  table.header([*Student Name*], [*Student ID*], [*Role in the project*], [*Contribution*]),
  [Marcus Gustafsson],
  [1904265],
  [Specifier, prompt engineer, implementer, verifier (solo team)],
  [100%],
)

I completed both repositories as a one-person project. I wrote specifications, directed coding agents, reviewed changes, and ran the available checks. I kept the student number as a placeholder because it is not recorded in the project files.

#heading(level: 1, numbering: none)[Executive Summary]

I developed two different versions of the same application that the LLM decided to call "ResearchPilot". The first version, that was fully "vibe coded" is an application that you can search for reserach papers in as well as keep track of all your papers in a given project. It ranks papers based on relevancy to your specific project and can keep the papers saved, keep notes for the papers, and how much progress you've done reading the paper. It also also uses OpenAIs API to give some descriptions of the papsers from OpenAIs LLM. The second version called "ResearchPilot-SDD" is a much smaller rebuild of the same system using SDD. It offers a lot of the same functionality, without the AI integration as it was a bit of a hassle to set up.

In the first project I used semi-formal Markdown specification, requirements, and architecture documents before starting the project, however following this I more or less just gave prompts to the LLM and adjusted accordingly. The SDD project used GitHub Spec kit workflow and all that comes with it.

Verification and validtaion was partly done with me, the human, as a validator to see that all the features were working. In the SDD project the LLMs focused a lot on me checking that everything is working and fine. I also used another LLM using the method LLM-as-a-judge to review the code to see that everything was in order.

= Introduction & Paradigm Shift <sec-1>

== Project Overview & Objectives <sec-1-1>

The project that later took on the name ResearchPilot (becuase that was what the LLM in the vibecoded version gave it without any instructions) is meant to address the time researchers spend locationg papers, judging relevance, organizing papers, and just keeping a list of useful citations. The vibecoded version grew quite quickly and supports the use of OpenAlex and optionally also Scopus through API keys. Things like relevance ranking, clustering, query expansion, open-access links, and project references are also included. The reference library also supports manual entry for papers that aren't available through OpenAlex or Scopus.

ResearchPilot-SDD uses the same idea but was by design much smaller in scope as the vibe coded version kind of outgrew the first intended scope, so this SDD version had a clear line it had to go to. It supports many of the same features the vibe coded one does, however a lot of the LLM provided functionality is not implemented y design. The two projects are in that sense related, but the scopes are a bit different still. The more fleshed out project is definately the vibe coded one.

== Vibe Coding <sec-1-2>

Vibe coding is when developers build software by describing in human languague what you want to generate to an LLM. When a version has been generated, often the user goes through it visually and checks that everything is working as inteded or if it isn't, gives a new prompt to the LLM for it to iterate on. Vibe coding often implies that the one who did the prompting has no idea what is actually going on in the codebase.

As the task first project was meant to be a completely vibe coded one, I thought the best method is to not think too hard about what I am actually trying to do when vibe coding, and just keep on prompting in clear human languague and not give too many barriers for the LLMs. I let the LLM iterate on my prompt, then I checked that everything was fine and prompted again. An example of this is when a feature was first introduced as a dropdown menu, I prompted that I disliked how it looked and that it was clunky, making it iterate further without giving any sort of indication what I wanted. This specific feature had to be iterated on 2-3 times before I was happy with how it looked.

== The SDD Methodology <sec-1-3>

SDD or Spec-Driven Development is a way of building software where you make the intended behaviour of said software clear before or sometimes while writing the code. The specification is a reference that everyone in a team can come back and look at while building software, testing software, or as in this project I did, for the LLMs to keep on track.

I approached SDD using GitHub Spec Kit Integration with OpenAI Codex. The Spec Kit provides a workflow and asks a lot of questions regarding planning, requirements, and organizing development tasks.

I decided to choose GitHub Spec Kit as it integrates with my chosen coding agent Codex, which makes it very straightforward to follow SDD without having to manually manage the entire process.

= Requirements & System Specification <sec-2>

== Stakeholders <sec-2-1>

#list(
  [*Researchers* are the primary users. They need relevant scholarly records, understandable organization, and control over what is saved.],
  [*The student developer* maintains scope, specifications, implementation, and evidence. In this solo project those responsibilities are mine.],
  [*Scholarly providers and AI services* are external systems whose schemas, rate limits, retention policies, and availability constrain the design.],
)

== Functional Requirements <sec-2-2>

Functional requirements describe what a system must do, the features and functionality that a user get from the system. The functional requirements for ResearchPilot were originally not much more defined than "I want an application that I can search papers from every source on". However, this was only the vibecoded and an expanded version came with the SDD verison of course.

The main functional requirements were:

#list(
  [*FR-01 - Project Management:* Users must be able to create and manage research projects],
  [*FR-02 - Reference Management:* Users must be able to add references manually, manage notes, and track reading and citation status],
  [*FR-03 - Paper Discover:* Users must be able to search for academic papers using external APIs],
  [*FR-04 - Relevance Ranking:* The system must evaluate and rank papers based on their relevance to the user's topic],
  [*FR-05 - Automatic Categorization:* The system must cluster the papers into relevant subtopic, with AI-generated names and explanations],
  [*FR-06 - Citation Accuracy:* The system must present the citation metadata unaltered from the scholary sources, they cannot be generated by an LLM.],
)

== Non-Functional Requirements <sec-2-3>

Non-functional requirements describe how a system does something, which includes performace, reliability, security, and maintainability.

The main non-functional requirements for this project were:

#list(
  [*NFR-01 - Performance:* The reserach should load a project containing 250 papers within 1.5 seconds.],
  [*NFR-02 - Reliability:* The system must handle failures from extrenal APIs and LLM integrations without interrupting the users workflow.],
  [*NFR-03 - Security:* API keys must only be on the backend and cannot be exposed.],
  [*NFR-04 - Reproducability:* The system has to remember queries, searchparameters, timestamps etc. so that searches can be understood and reproduced. ],
)

== Technology Stack <sec-2-4>

#report-table(
  columns: (1.45fr, 3fr),
  table.header([*Technology*], [*Use in the projects*]),
  [Python, FastAPI, SQLAlchemy],
  [Pthon supports AI libraries, FastAPI simplifies REST APIs, and SQLAlchemy provides database integration],
  [PostgreSQL],
  [Provides reliable relational data storage, transactions, and suport of complex relationships between projects and papers],
  [Vanilla JavaScript and HTML/CSS],
  [Keeps frontend lightweight and avoids complexity of introducing seperate frontend framework],
  [OpenAlex],
  [Provides access to real papers thorugh an API, very limited papers though],
  [OpenAI APIs],
  [Supports LLM usage in the original vibe coded project. OpenAIs API was easy to set up],
  [Codex and Claude Code],
  [Both Claude Code and Codex were used, various models as well. I wanted to test both Antrophics and OpenAIs CLI tools hence why both were used. Models such as GPT-6.1 Sol, GPT-5.5 Sol, Claude Opus 5.5 were used.],
  [GitHub Spec Kit workflow],
  [Provided a structured SDD workflow, was the one specified in the project description.],
)

== Interface & API Specifications <sec-2-5>

=== User Interface

The user interface provides different pages where the users can create and manage projects, organize references, configure application settings, and explore academic papers. The main project page includes a reference libarary and a reserach map where papers can be viewed and organizied into subtopics.

=== REST API

The backend exposes REST API that allows the frontend to communicate with the application. The API handles things such as project management, reference management, literature searches, and paper categorization.

Some of the main endpoints in the project are:

#report-table(
  columns: (1.45fr, 3fr),
  table.header([*Endpoint*], [*Purpose*]),
  [GET /api/projects],
  [Retrieve research projects],
  [POST /api/projects],
  [Create a new projec],
  [GET/api/projects/{id}/search],
  [Retrieve saved references],
  [POST /api/projects/{id}/search],
  [Start a literature search],
  [GET /api/projects/{id}/papers],
  [Retrieve discovered papers],
  [GET /api/projects/{id}/subtopics],
  [Retrieve generated subtopics],
)

=== External APIs

ResearchPilot integras with external APIs as well:

#report-table(
  columns: (1.45fr, 3fr),
  table.header([*Service*], [*Purpose*]),
  [OpenAlex (api.openalex.org/works)],
  [Searching for papers],
  [Scopus (api.elsevier.com/content/search/scopus)],
  [Searching for papers],
  [Crossref and DataCite],
  [Used to recieve citation metadata from a DOI],
  [OpenAI (OPENAI_BASE_URL)],
  [LLM calls],
)


== How These Requirements and Specifications Were Created <sec-2-6>

The requirements and specifications were not created at all in the vibe coded project. I created some really rough things I wanted the vibe coded version to do in a `requirements.md` file, however more than that I did not do for the vibe coded one, the rest was up to the LLM. In the SDD version I used as I said before GitHub Spec Kit together with Codex (via the `/speckit` command) to create all the requirements and specifications. This Spec Kit created several useful things before starting the project:

#list(
  [*Specification:* Defines what the system should do based on initial requirements],
  [*Plan:* Described the approach to how technical implementation and architecture needed to look],
  [*Tasks:* The Spec Kit created a lot of different tasks instantly and asked me to verify these tasks],
  [*Constiution:* Established some principles and constraints that helped guide the project],
)


= Vibe Coding and Your Project <sec-3>

As I have mentioned quite a few times before, my approach to vibe coding was letting the LLM take the wheels. No specific approach expect that there was no approach was used in the vibe coded project. A really rudimentary markdown file with requirements was established with a few requirements before start and that was the extent of my planning for the vibe coded project. When initializing the project it was split up by the LLM into several components, having different agents working on different part of the project. Development was mainly done interavely, meaning as new versions were done I just thought about more features that could be added and asked the LLM to implement them.

I decided to use Claude Code and Codex, as well as Qwen 3.5b-9b just as a test to see how it faired compared to the frontier models. I wanted to use both OpenAIs and Antrophics agents to compare them and see if there was any noticable difference in them.

== Prompting Framework <sec-3-1>

The prompting framework mainly consisted of natural-languague instructions and iterative prompting. Instead of giving prompt with a lot of details instructions for how every function should be, I just described what I wanted and allowed the agents to implement it however they wanted.

As I mentioned earlier, Codex and Claude Code were used for the development. Sometimes they were used at the same time, which caused a bit of a headache and I decided to not do that anymore. The agents had full access to the entire repository at all times and could modify code, files, and carry out whatever tasks they needed.

The prompts I used did vary a bit depending on how big of a task I gave. Larger prompts were used for new functionality, while easier small fixes used shorter follow-up prompts. This made it very easy to iterate on the application.

Worth mentioning as well that I use the skill superpower which gives the agents instructions to actually ask questions to the user before they start implementing.

== Master Prompts / System Prompts <sec-3-2>



#block(inset: 8pt, fill: luma(96%), stroke: 0.5pt + luma(65%))[
  *Starter prompt - product definition :*

  You are helping me build a new application called ResearchPilot. ResearchPilot is a web application where a user enters a research topic or research question, the backend searches trusted scholarly sources for real papers, and the system automatically organizes those papers into meaningful subtopics.

  *Reasoning and expected result:* There were some very rudimentary things specified in a couple of markdown files before starting the project, and I wanted to the languague as natural as possible. This prompt got me started but it did not really do everything that I told it in the prompt. It instead drafted an MVP which then was executed over multiple prompts where the LLM asked _"Should I continue?"_ or something similar. ]

#block(inset: 8pt, fill: luma(96%), stroke: 0.5pt + luma(65%))[
  *Relevance complaint:*

  Okay this worked. I just used the topic 'Infrastructure as Code' and the papers that came back had at most a relevance of 30%. That is quite bad.

  *Reasoning and expected result:* While this prompt maybe sounds a bit strange, my reasoning for it was that the paper search was meant to return results with a high relevance and a topic such as IaC is not really that niche. I expected a higher relevance. The agent diagnosed the cause and found a couple of issues which it told me and asked if I wanted to fix, which I answered with _"Yes lets start it"_ prompting the agent to begin fixing it.

  I would say that using concrete examples for something is often very good for troubleshooting and explaining issues so that the agent understands.
]

#block(inset: 8pt, fill: luma(96%), stroke: 0.5pt + luma(65%))[
  *Issues with the `phase`:*

  Before we continue I think this phase naming has to stop. There has to be a better way to describe features that you are implementing because at this point we are on phase 25 which seems stupid and says absolutely nothing.

  *Reasoning and expected result:* Sometimes the agents just make strange or inhuman decision, and this was one of them I feel. The naming scheme was very stupid and the agent constantly said something like _"starting phase 15..."_ which was very annoying and I did not understand what it was working on. This small complaint fixed it quite well.
]

#block(inset: 8pt, fill: luma(96%), stroke: 0.5pt + luma(65%))[
  *UI issues - a compilation:*

  #list(
    [Lets create a way to order the papers, relevance, citations etc],
    [[screenshot] everything is kinda blending into each other. the sort by button and open access button being mismatched is really bad as well"],
    [The issue was not the position of the buttons the issue was that the buttons are different sizes and the sort by text is severly out of place],
    [[screenshot] furthermore you can't really tell where the search and buttons of subtopic end and where papers start],
    [[screenshot] the create subtopic part and explanation available on requrest looks to similar. the "All paper" and rest should be much clearer],
    [the window that comes up when pressing edit is really jarring as it is a browser popup more or less instead of integrated into the application],
  )

  *Reasoning and expected result:* UI issues is one of the largest problems with agentic coding in my opinion. They do not really understand UI too well and often things just look _off_ to the human eye. These prompts are also quite bad, as they dont give any direction of possible fixes and just say _"this is bad"_. Some of the issues needed multiple prompts to fix a relatively small issue.
]

Long prompts that have a lot of information are *always* better than a vague prompt. I knew this, but intentionally played into fully vibe coded prompts. The majority of issues came from UI and general agent behaviour, with the backend not really needing any extra prompting to get something working.

== Prompt Iteration Log <sec-3-3>

The UI issue prompt was the only large prompt issue I had where I iterated a couple of times.

#report-table(
  columns: (1fr, 1fr, 1fr, 1fr, 1fr, 1fr),
  table.header(
    [*Initial Prompt*],
    [*AI Failure*],
    [*Refined Prompt*],
    [*Resulting Code Quality*],
    [*What did not happen*],
    [*Modified Prompt*],
  ),
  [everything is blending into each other],
  [The agent moved the buttons into a new toolbar],
  ["I mean the position of the buttons were not the problem the problem is that the buttons are different sizes and the sort by text is severly out of place" + 2 screenshots],
  [UI refined and a lot better],
  [Understanding plain text wrong],
  [Specified what was wrong and included screenshots],
)

= Specification-Driven Development and Your Project <sec-4>

== SDD Tool-kit <sec-4-1>

The SDD tool-kit chosen was GitHub Spec Kit, installed as an agent skill on Claude Code and Codex. It was the tool-kit specified in the project description, along with the fact that it leaves a lot of files behind. If you look in the repo there are tons of different files such as a constitution, `spec.md`, `plan.md`, `contracts/`, `tasks.md`, `docs/evidence-log.md` to name a few. This makes the entire project traceable and a lot more coherent, something the vibe-coded project completely lacked.

== Development Environment <sec-4-2>

#list(
  [*Claude Code* used a lot less than in the vibe-coded project. The reason for this is that Codex released their GPT-6.0 Astra around the time I started the SDD version which inclined me to use it instead.],
  [*Codex* used because as I mentioned GPT-6.0 was newly released and I wanted to test it out. GPT-6.0 is a massive token hog so different versions of GPT were used as well.],
  [*Stack:* Arch Linux, Python 3.13, FastAPI, PosgreSQL in Docker, browser testing. The stack is more or less exactly the same as the vibe-coded one, not much reason to change it as this project was supposed to support LLM integration as well.],
)

== Deriving Requirements Using IDE/Coding Agents <sec-4-3>

By using the Spec Kit together with Codex I could derive requirements for the SDD version very easily. I gave a simple explanation of what I wanted and from there a bunch of questions were asked to gain an understanding of the exact aplpication i wanted to build.

To initialize the Spec Kit I ran the command `/speckit.constitution` in Codex and described the intended functionality and any ambiguity was clarified with follow-up questions. The point of the clarifications is to turn feature descriptions into more specific and testable requirements, including function behaviour, performance, and failure handling.

The table below shows examples of the inital specification prompts and the clarifications that were made by the LLM.

#report-table(
  columns: (1fr, 2fr, 2fr),
  table.header(
    [*Feature*],
    [*Prompt*],
    [*Example clarification*],
  ),
  [001 projects],
  [Project management for users, features such as save, edit, and add notes to projects],
  [_"require 95% of the requests to finish within 500 milliseconds?"_ , p95 < 500 ms over 100 requests with 100 projects. This is a non-functional requirement dervied through clarification],
  [002 queries],
  [Retain description-driven query suggestions and user control],
  [Regeneration replaces only untouched AI queries, with a cap of 20 queries],
  [003 retrieval],
  [Retrieve real papers from OpenAlex using approved stored queries],
  [_"If one Open Alex request fails, keep previous results?"_ -> fail the whole attempt and keep the old results.],
  [004 ranking],
  [Retain embedding ranking without clustering or automatic result filtering],
  ["everything should be done locally", a model all-miniLM-L6-v2 was approved to do ranking locally.],
  [005 references],
  [Retain a minimal project reading list from retrieved papers],
  [_"Should retrieved papers be automatically added to the reading list?"_ -> Only papers explicitly selected by the user are saved.],
)

== SDD Workflow and Implementation <sec-4-4>

The workflow used was GitHub Spec Kit workflow that is integrated with Codex, so it was very straightforward at all times. There are some main stages for the Spec Kits workflow:

+ *Specification (/speckit.specify):* Functionality is specified from my prompts
+ *Clarification (/speckit.clarify):* Any requirements from the specification stage are uncertain will get clarified by follow-up questions
+ *Planning (/speckit.plan):* The specification were used to create a technical implemntation plan that describes the application's architecture and components
+ *Task generation (/speckit.tasks):* The implementation plan is divided into smaller tasks, allowing the functionality to be implemented in a smaller, structured manner
+ *Implementation (/speckit.implement):* Codex implements the planned functionality from the implementation plan and tasks.

This workflow allowed the agent to work for a longer period of time without asking me questions constantly and can implement features that I can trust a little bit more. The specifications and implementation plans serve as references that the agent can refer back to if anything is unclear, which helped to actually create what I wanted.

== Prompts <sec-4-5>

+ The single most important prompt of this entire SDD section was `/speckit-constitution` with an empty input. This launched the entire SDD process and asked me questions about what I was looking to build. I was asked for an initial idea to which I answered:

#block(inset: 8pt, fill: luma(96%), stroke: 0.5pt + luma(65%))[
  ResearchPilot is a local web app where you enter a research question and it finds real papers for you. Paper info like titles, authors and DOIs must always come from OpenAlex, never from the AI. The AI only suggests search queries, and its output should be JSON that gets validated. Keep OpenAlex and OpenAI behind interfaces so they can be swapped out. The user should always have the final say over the queries. Write tests for all logic, don't use real APIs in tests, and keep API keys in env variables. Keep it simple and only build what's in the specs. I want to approve each spec, plan and task list before anything is implemented.
]

For this project I tried to go quite detailed with my prompts, which is contrary to how I decided to do the vibe coded project, and this was entriely on purpose. The vibe coded project felt at times like you were fighting with the agent like _"no, do it this way don't you understand"_, meanwhile the goal for this project was to make it much more enojyable and right the first time around.

The rest of the "prompts" were answers to the agents SDD plugin/skill running. They were multiple choice always, had 1 recommended option, then a secondary option, and also another option for user input. This one prompt created the entire plan start to finish and all I had to do was approve features every now and then by actually testing them myself. A very typical scenario was the agent asking _"I implemented this feature, test that it works correctly. If everything works as defined in the documents type 'I approve'"_. And all I had to was test the feature, and continue. Between these approvements the agent asks a lot of questions that have multiple choice answers that make it easy to decide on what feels right.


= Verification and Validation <sec-5>

== V&V Strategy <sec-5-1>

I used unit and domain tests, API tests, fake providers, mocked HTTP transports, browser automation, PostgreSQL migration and concurrency tests, static checks, and code review. In the SDD project, test names map to feature requirements, and the evidence log distinguishes mock-provider outcomes from live provider behavior. The feature 002 suite deliberately makes no paid API call. Human audit and acceptance remain separate gates.

== Code Audit Log <sec-5-2>

#report-table(
  columns: (1.25fr, 2.5fr, 2fr),
  table.header([*Review area*], [*Evidence or finding*], [*Status and limitation*]),
  [Metadata/provider boundary],
  [Original app rules and tests keep provider-owned facts separate from model interpretation. SDD query generation returns search text only.],
  [Automated/static checks exist; this is not external security certification.],
  [Stale query generation],
  [SDD service snapshots state, calls the provider without holding the database transaction, then checks the revision before merging. Concurrency tests use controlled schedules.],
  [Recorded as tested against PostgreSQL in the 2026-10-14 milestone; final re-verification remains pending.],
  [Credential and context logging],
  [Mock adapter and API tests use canary values to check that secrets and user context do not appear in logs.],
  [No live API call or provider retention claim is made.],
  [Known project limitation],
  [Feature 001 has a reported publication-year input issue, deferred by the user.],
  [Open in `ResearchPilot-SDD/docs/known-issues.md`; not fixed by feature 002.],
)

== Test Execution Results <sec-5-3>

The original application's saved report-validation run on 23 September 2026 recorded *180 passed, 2 skipped, 0 failed* in 11.47 seconds using SQLite and Chromium with fake providers. The two PostgreSQL concurrency tests were skipped in that run. This is historical evidence for that snapshot, not a new test of the current checkout.

The ResearchPilot-SDD evidence log records *277 passed, 1 deselected, 1 warning* for the query generation milestone on 14 October 2026, plus a passing project performance test from an earlier slice. These results were recorded with local PostgreSQL, fake providers, and mock HTTP. They do not finish query feature 002: its separate query performance test, final audits, human review, post-audit verification, and acceptance remain open. No result is claimed for the unfinished retrieval, ranking, or saved-reference slices.

The user accepted feature 001 with the known publication-year input issue deferred. This is acceptance with a stated limitation, not a claim that every requirement passed. The SDD repository's GitLab CI configuration is present, but no remote pipeline result is recorded in the evidence used here.

#report-table(
  columns: (1.5fr, 1.4fr, 2.3fr),
  table.header([*Repository and run*], [*Recorded result*], [*Scope and limitation*]),
  [ResearchPilot, 2026-09-23],
  [180 passed, 2 skipped; SQLite and Chromium.],
  [Historical report-validation run; PostgreSQL concurrency tests skipped.],
  [ResearchPilot-SDD, 2026-10-14],
  [277 passed, 1 deselected, 1 warning.],
  [Recorded query milestone run with PostgreSQL and fake/mock providers; no live model quality claim.],
  [ResearchPilot-SDD, query performance],
  [Not run.],
  [Approved protocol exists; query performance acceptance is pending.],
)

= Project Management & AI Toolchain Workflows <sec-6>

== Version Control & Prompt Integration <sec-6-1>

The original project uses commits and phase documentation to connect implementation work with requirements. Its visual commit sequence also provides a partial record of prompt iteration. The SDD repository uses feature branches/checkpoints, GitLab CI configuration, task identifiers, and an evidence log. It was migrated to a private GitLab repository; the recorded local evidence says remote push and CI execution were not verified at that time. A commit is useful traceability, but it does not by itself prove a prompt was followed or a feature accepted.

== Team Contribution Breakdown <sec-6-2>

I performed all roles: requirements author, specifier, prompt engineer, implementer, reviewer, tester, and integrator. No independent human reviewer or usability assessor is recorded for the SDD query milestone. That limitation makes my own acceptance judgment less independent, and the remaining human review gate should be completed before claiming feature acceptance.

= Reflections on Specification-Driven Development <sec-7>

== Benefits of AI-Assisted SDD <sec-7-1>

The strongest benefit was turning ambiguous product behavior into explicit rules that could be reviewed and tested. Query ownership, regeneration, capacity, stale writes, and failure preservation are stated in the SDD feature 002 specification and reflected in domain, API, PostgreSQL, and browser tests. The broader application also shows that concise visual prompts can be effective when the result can be judged directly on screen.

I did not measure time saved against manual implementation, so I cannot give a defensible speedup. The tests show repeatable behavior under the stated fixtures; they do not establish real-world model quality or ranking usefulness.

== Core Bottlenecks and Challenges <sec-7-2>

The main challenge was keeping scope and completion status precise across two related repositories. The original application has many capabilities that the rebuild intentionally excludes. Similar naming can make it easy to assume feature parity where none exists. A second challenge is verification cost: database concurrency, performance, browser behavior, provider behavior, and human usability each need different evidence.

The SDD project is unfinished. Feature 002's recorded green suite is an important checkpoint, but not an acceptance result. Its query performance protocol, final audit, human usability review, and post-audit run remain open. The reduced rebuild's retrieval, ranking, and saved-reference slices have not been implemented. I also have an open publication-year input issue in feature 001. These boundaries should remain visible in the final account.

== Lessons Learned & Best Practices <sec-7-3>

#list(
  [Keep the broad product and reduced rebuild's scope explicit; do not infer parity from shared names.],
  [Write acceptance behavior, failure cases, and non-goals before implementation.],
  [Use fake providers for repeatable tests and reserve live-service claims for separately recorded evidence.],
  [Test database-specific behavior on the actual database engine and browser interactions in a real browser.],
  [Keep implementation, verification, human review, and acceptance as distinct project states.],
  [Do not reconstruct missing coding-agent conversations as verbatim prompts. Label evidence by its source.],
)

== Proposed Specification-Driven Development Workflow <sec-7-4>

I propose the following reusable cycle for future slices. Each phase produces an artifact that a reviewer can inspect before the next dependent phase begins.

#align(center)[
  #stack(
    spacing: 4pt,
    block(width: 88%, inset: 7pt, fill: luma(96%), stroke: 0.5pt + luma(55%), radius: 2pt, align(
      center,
    )[*1. Define scope* — goals, exclusions, stakeholders]),
    text(size: 14pt)[↓],
    block(width: 88%, inset: 7pt, fill: luma(96%), stroke: 0.5pt + luma(55%), radius: 2pt, align(
      center,
    )[*2. Specify and review* — requirements, scenarios, contracts, risks]),
    text(size: 14pt)[↓],
    block(width: 88%, inset: 7pt, fill: luma(96%), stroke: 0.5pt + luma(55%), radius: 2pt, align(
      center,
    )[*3. Implement a bounded slice* — agent-assisted code and tests]),
    text(size: 14pt)[↓],
    block(width: 88%, inset: 7pt, fill: luma(96%), stroke: 0.5pt + luma(55%), radius: 2pt, align(
      center,
    )[*4. Verify in context* — unit, API, database, browser, and security checks]),
    text(size: 14pt)[↓],
    block(width: 88%, inset: 7pt, fill: luma(96%), stroke: 0.5pt + luma(55%), radius: 2pt, align(
      center,
    )[*5. Audit and accept* — human review, evidence, known limits]),
    text(size: 14pt)[↓],
    block(width: 88%, inset: 7pt, fill: luma(96%), stroke: 0.5pt + luma(55%), radius: 2pt, align(
      center,
    )[*6. Integrate and update* — merge, changelog, roadmap, next-slice decision]),
  )
]

#report-table(
  columns: (1fr, 2.2fr, 2.2fr),
  table.header([*Phase*], [*Input → output*], [*Human and AI responsibilities*]),
  [Define],
  [Product goals and constraints → bounded scope and non-goals.],
  [I own scope; AI can identify questions and dependencies.],
  [Specify],
  [Scenarios and risks → reviewed requirements, contracts, and acceptance checks.],
  [I approve behavior; AI helps draft and find edge cases.],
  [Implement],
  [Approved slice → code and regression tests.],
  [AI assists with implementation; I review the diff and tests.],
  [Verify],
  [Implementation → recorded results in relevant environments.],
  [I select evidence and investigate failures; automation runs repeatable checks.],
  [Accept],
  [Passing evidence → reviewed feature state and known limitations.],
  [A human reviewer challenges assumptions; I record the decision and open work.],
  [Integrate],
  [Accepted slice → merged code and updated project records.],
  [I ensure repository state and documentation agree before starting dependent work.],
)

The central lesson from these projects is that AI can speed up implementation, but it does not remove the developer's responsibility to define scope, choose meaningful checks, review evidence, and report unfinished work accurately.

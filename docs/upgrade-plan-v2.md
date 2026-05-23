# PlayDesk AI Upgrade Plan v2

> Assumption: the original PlayDesk demo plan has already been fully completed, including Django + DRF, PostgreSQL + pgvector, booking safety, RAG, hand-rolled agent loop, tool calling, streaming, evaluation set, Stripe sandbox, bilingual demo, and conflict-aware slot suggestions.

This version does **not** repeat the original implementation plan.  
The goal is to upgrade PlayDesk from a completed AI demo into a stronger **production-minded AI application case study** for the COSReady interview.

---

## 0. What Is Already Done

The original PlayDesk plan already proves:

- Full-stack execution with Django, DRF, PostgreSQL, pgvector, and Next.js
- Manual booking and AI booking flows
- Database-level double-booking prevention
- RAG for FAQ, policy, and menu questions
- SQL/tool calling for availability and booking
- Hand-rolled agent loop
- Streaming assistant response
- Conversation and message persistence
- Evaluation set
- Stripe sandbox
- Bilingual support
- Conflict-aware slot suggestions

So the next step is **not** to build another eval set or add more CRUD features.

The next step is to show deeper AI product understanding:

- production observability
- feedback loops from real users
- human-in-the-loop operations
- AI quality monitoring
- business outcome tracking
- multi-channel AI front desk design
- reliability, safety, and cost control

---

# Phase 1 — AI Production Trace Dashboard

## Goal

Turn existing message/tool logs into a readable AI trace dashboard.

This is different from the existing eval set.  
The eval set tests expected behavior.  
The trace dashboard explains what happened in each real conversation.

## Why It Matters

In real AI products, the team needs to answer:

- Why did the assistant say this?
- Did it use RAG or SQL tools?
- Which tool did it call?
- Did the backend reject an unsafe action?
- Was the response slow because of retrieval, LLM, or database?
- How much did this conversation cost?

## Features

Create an admin page:

```text
/admin/ai-traces
/admin/ai-traces/:conversationId
```

Show for each conversation:

- user messages
- assistant messages
- tool calls
- tool results
- retrieved RAG chunks
- prompt version
- model name
- latency per step
- estimated token cost
- final booking outcome
- failure / retry records

## Acceptance Criteria

- A reviewer can inspect one AI conversation end-to-end.
- The dashboard clearly shows whether the assistant used RAG or SQL tools.
- Unsafe booking attempts are visible.
- Tool failures and fallbacks are visible.
- Latency and cost are visible.

## Interview Talking Point

> I already had an eval set, but I added an AI trace dashboard because real production debugging requires understanding individual conversations. Evals tell us whether the system passed; traces tell us why.

---

# Phase 2 — Human-in-the-Loop Operations

## Goal

Add a staff workflow for conversations that AI should not fully handle.

## Why It Matters

A real AI front desk should not pretend to solve every case.

For salons, spas, or service businesses, some cases should go to a person:

- angry customer
- payment issue
- unclear booking request
- refund request
- policy exception
- repeated failed AI attempts
- user explicitly asks for human help
- AI confidence is low

## Features

Add conversation states:

```text
active
ai_resolved
needs_human
staff_takeover
closed
```

Add admin queue:

```text
/admin/handoff
```

Each row shows:

- customer identifier
- latest message
- handoff reason
- conversation age
- suggested staff action
- button: “Take over”
- button: “Mark resolved”

## Handoff Triggers

Trigger handoff when:

- tool call fails more than 2 times
- agent iteration limit is reached
- user asks for a human
- user uses urgent or angry language
- payment/refund issue appears
- booking conflict cannot be resolved
- RAG confidence is low or no policy source is found

## Acceptance Criteria

- AI can mark a conversation as `needs_human`.
- Staff can take over from admin.
- The customer sees a polite handoff message.
- AI stops taking booking actions after handoff.
- Handoff reason is logged.

## Interview Talking Point

> I designed the assistant as AI plus human, not AI replacing humans completely. In early-stage production, safe escalation is more realistic than full automation.

---

# Phase 3 — AI Quality Monitoring

## Goal

Upgrade the completed eval set into a lightweight monitoring system.

This is not “creating eval from scratch.”  
This is using completed eval work to track quality over time.

## What Changes

Instead of just running eval manually, track:

- pass rate by prompt version
- pass rate by model
- tool selection accuracy
- booking safety accuracy
- hallucination cases
- average latency
- average cost
- handoff rate

## Features

Add a generated report:

```text
docs/reports/ai-quality-report.md
```

Example:

```markdown
# AI Quality Report

| Metric | Result |
|---|---:|
| Tool Selection Accuracy | 92% |
| Booking Safety Accuracy | 100% |
| RAG Answer Accuracy | 87% |
| Human Handoff Rate | 11% |
| Avg Latency | 2.8s |
| Avg Cost / Conversation | $0.003 |
```

Add comparison table:

```markdown
| Prompt Version | Tool Accuracy | Safety | Avg Latency | Notes |
|---|---:|---:|---:|---|
| v1_basic | 78% | 90% | 2.1s | Too likely to answer without tools |
| v2_strict_tools | 92% | 100% | 2.8s | Best production candidate |
| v3_bilingual | 89% | 100% | 3.0s | Better Chinese handling |
```

## Acceptance Criteria

- Existing eval set can produce a quality report.
- Report compares at least two prompt versions.
- Report includes one failure analysis.
- Report includes one improvement decision.

## Interview Talking Point

> I completed the eval set first. Then I turned it into a quality monitoring workflow so prompt and model changes can be compared instead of guessed.

---

# Phase 4 — Prompt Versioning and Release Control

## Goal

Show that AI behavior can be updated safely.

## Why It Matters

Prompt changes can break AI behavior.  
A production team needs to know:

- which prompt produced which answer;
- when a prompt changed;
- whether a new prompt improves tool usage;
- how to roll back if quality drops.

## Features

Add `PromptConfig`:

```text
name
version
system_prompt
model_name
temperature
retrieval_top_k
is_active
created_at
```

Save on each AI response:

```text
prompt_version
model_name
temperature
retrieval_top_k
```

## Example Versions

```text
prompt_v1_basic
prompt_v2_strict_tool_policy
prompt_v3_bilingual
prompt_v4_handoff_sensitive
```

## Acceptance Criteria

- Active prompt can be switched without changing code.
- Each conversation stores prompt version.
- Eval/quality report includes prompt version.
- Old prompt can be restored.

## Interview Talking Point

> Prompt iteration should be treated like software release management. I track prompt versions so we can compare quality and roll back if needed.

---

# Phase 5 — Business Outcome Metrics

## Goal

Connect AI behavior to business value.

This is important for COSReady because the product is not just a technical tool; it is supposed to help salons get more bookings, reduce front-desk workload, and improve retention.

## Metrics

Track:

```text
AI conversations per day
AI-handled booking requests
Bookings created by AI
Manual bookings vs AI bookings
AI booking conversion rate
Human handoff rate
Missed or unresolved conversations
Average response time
Repeat customer interactions
```

## Dashboard Cards

```text
AI Booking Conversion
Human Handoff Rate
Average AI Response Time
Estimated Front-Desk Time Saved
AI-created Revenue Estimate
```

## Example Revenue Estimate

```text
AI-created bookings × average booking value = estimated assisted revenue
```

## Acceptance Criteria

- Admin dashboard shows AI booking conversion.
- Admin dashboard separates manual bookings and AI bookings.
- AI-created booking revenue can be estimated.
- Handoff rate is visible.

## Interview Talking Point

> I wanted the demo to show not only that the AI works technically, but also how the business would measure whether the AI front desk is valuable.

---

# Phase 6 — Multi-Channel Front Desk Design

## Goal

Show how the same AI backend could support web chat, SMS, WhatsApp, and phone in the future.

## Why It Matters

COSReady positions itself as an AI front desk across phone, text, and web.  
Even if PlayDesk only implements web chat, we can show that the architecture is channel-ready.

## Channel Abstraction

Add a `channel` field to `Conversation`:

```text
web_chat
sms
whatsapp
phone
manual_staff
```

Each channel should normalize incoming messages into the same backend format:

```json
{
  "channel": "sms",
  "customer_identifier": "+1416xxxxxxx",
  "text": "Do you have a PS5 room tonight?"
}
```

## Optional Twilio Sandbox

If time allows:

- add a Twilio SMS webhook endpoint;
- receive text messages;
- pass message into the same agent loop;
- return assistant response by SMS.

Endpoint:

```text
POST /api/webhooks/twilio/sms/
```

## Acceptance Criteria

- Web chat and SMS can share the same agent loop design.
- Conversation stores channel.
- Admin can filter by channel.
- Architecture diagram explains future voice path.

## Interview Talking Point

> I designed the agent backend to be channel-independent. Web chat, SMS, WhatsApp, and phone calls can all become normalized conversation events handled by the same AI workflow.

---

# Phase 7 — Voice AI Readiness Design

## Goal

Prepare a clear voice AI architecture, even if full voice implementation is not completed.

## Flow

```text
Phone call
→ Twilio Voice
→ speech-to-text
→ normalized conversation message
→ agent loop
→ backend tool validation
→ text response
→ text-to-speech
→ customer hears response
```

## Key Rules

- Voice uses the same booking tools as web chat.
- LLM does not directly create bookings.
- Backend validates all actions.
- Long or sensitive cases go to human handoff.
- Conversation transcript is stored for review.

## Deliverable

Create:

```text
docs/voice-ai-readiness.md
```

Include:

- architecture diagram;
- provider choices;
- latency risks;
- fallback behavior;
- what should be implemented first.

## Acceptance Criteria

- Voice design is documented.
- It reuses the existing agent loop.
- It explains STT / LLM / TTS clearly.
- It defines human fallback.

## Interview Talking Point

> I have not fully built a production voice pipeline yet, but I designed how it would connect to the same AI backend. The important part is that phone, SMS, and web should share the same business logic and booking tools.

---

# Phase 8 — Local Market / Bilingual Product Story

## Goal

Make the demo directly relevant to local service businesses.

## Why It Matters

For beauty, wellness, and salon businesses in Toronto, multilingual support and local customer behavior matter.

## Features

If bilingual support is already done, add a polished demo path:

```text
English customer asks policy question
Chinese customer asks booking question
Admin sees both conversations
AI responds in the user's language
Booking tools still use the same structured backend logic
```

## Example Chinese Demo

User:

```text
今天晚上八点有PS5位置吗？我们三个人，想玩两个小时。
```

Assistant:

```text
我来帮你查一下今晚 8 点是否有 PS5 空位。
```

Tool:

```text
check_availability(resource_type="ps5", date="today", time_range="20:00-22:00", party_size=3)
```

## Acceptance Criteria

- Demo clearly shows English and Chinese user flows.
- Language does not change backend safety logic.
- Admin can inspect bilingual conversations.
- README explains why bilingual AI matters for local businesses.

## Interview Talking Point

> I included bilingual flow because local service businesses often serve multilingual customers. For an AI front desk, language support can directly affect booking conversion and customer experience.

---

# Phase 9 — Final Interview Case Study Package

## Goal

Turn the project into a clean interview artifact.

## Deliverables

```text
README.md
docs/architecture.md
docs/ai-design-decisions.md
docs/ai-quality-report.md
docs/voice-ai-readiness.md
docs/demo-script.md
screenshots/
```

## README Structure

```markdown
# PlayDesk — AI Front Desk Demo

## Why I Built This
Built for the COSReady interview as an adjacent vertical demo.

## What It Demonstrates
- Full-stack SaaS booking flow
- AI front desk
- RAG + SQL tool separation
- Booking safety
- AI observability
- Human handoff
- Quality monitoring
- Business metrics

## Architecture
Include diagram.

## Demo Flow
1. Manual booking
2. AI booking
3. Unavailable slot guardrail
4. Policy question via RAG
5. Human handoff
6. AI trace dashboard

## Key AI Design Principles
- Database is source of truth
- LLM suggests, backend validates
- RAG for unstructured knowledge
- SQL tools for structured truth
- Human handoff for uncertain cases
- AI quality must be measured
```

## 3-Minute Demo Script

```text
This is PlayDesk, an AI front-desk demo for a service-booking business.

I built it in an adjacent vertical to COSReady: instead of a salon, it manages bookings for game lounges.

The core idea is similar: customers ask questions, check availability, and book services through an AI assistant.

The important part is that this is not just a chatbot. The LLM does not invent availability or directly write to the database. It uses backend tools. PostgreSQL is the source of truth.

For unstructured questions like policies, the assistant uses RAG. For structured actions like checking availability and creating bookings, it uses SQL-backed tools.

I also added production-minded features: AI traces, human handoff, prompt version tracking, quality reports, and business metrics. These are important because real AI systems need to be measurable, debuggable, and safe.
```

## Acceptance Criteria

- Project can be understood in 5 minutes.
- Demo can be shown in 3 minutes.
- AI design principles are obvious.
- Screenshots exist for key pages.
- Interviewer can see both technical and product thinking.

---

# Final Suggested Order

## Day 1

- Build AI trace dashboard.
- Add trace detail page.
- Add latency/token/cost display.

## Day 2

- Add human handoff queue.
- Add handoff triggers.
- Add admin takeover/resolution.

## Day 3

- Add prompt versioning.
- Generate quality comparison report from existing eval set.

## Day 4

- Add business outcome metrics.
- Add AI booking conversion and handoff rate cards.

## Day 5

- Add channel abstraction.
- Optionally add Twilio SMS webhook stub.

## Day 6

- Write voice AI readiness document.
- Polish bilingual demo path.

## Day 7

- Package README, screenshots, architecture, demo script.
- Practice 3-minute and 10-minute interview versions.

---

# What This v2 Upgrade Proves

After completing this upgrade, PlayDesk demonstrates:

```text
I can build full-stack SaaS features.
I can connect LLMs to real backend workflows.
I understand that databases, not LLMs, are the source of truth.
I understand why RAG and SQL tools must be separated.
I can design AI observability.
I can turn AI evaluation into quality monitoring.
I can design human handoff for real business operations.
I understand AI cost, latency, and business conversion.
I can think beyond code and explain product value.
```

This is the strongest direction for showing practical AI application understanding in the COSReady interview.

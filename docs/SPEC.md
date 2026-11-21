# Regulatory RAG (RBI + GST): Specification v1

Status: APPROVED 2026-11-16. Written 2026-11-15; revised 2026-11-16 with the decisions in section 11.
Facts marked **[verified]** were checked on the web on 2026-11-15 (source URL given).
Facts marked **[to verify]** could not be confirmed and must be checked by the task that first uses them.

---

## 1. Goal and users

**Goal.** Answer questions about Indian banking regulation (RBI) and GST (CBIC) from the official documents, and for every answer:

1. cite the document, section and page it came from,
2. say so when the rule it found has been amended, superseded or withdrawn,
3. refuse to answer ("abstain") when the retrieved evidence is weak,
4. be measurable: a golden set of ~120 questions scores every change.

**Users.**
- *Primary:* Goutham, as a learning and portfolio project.
- *Imagined end user:* a compliance analyst, CA or fintech product person who needs "what does the rule say, and where exactly is it written?"
- *Future users:* five follow-on projects that plug into this repo (see section 10).

**This is not legal or tax advice.** Every answer carries that one-line disclaimer.

### 10 example questions

| # | Type | Question | What a good answer does |
|---|---|---|---|
| 1 | RBI | Which documents count as Officially Valid Documents for an individual's KYC at a commercial bank? | Cites the Commercial Banks KYC Directions 2025, definitions section, with page |
| 2 | RBI | What is the maximum amount that can be loaded on a small prepaid payment instrument? | Cites the PPI Master Direction, the relevant paragraph (often a table) |
| 3 | RBI | What additional authentication must a payment system apply to a digital payment transaction? | Cites the Authentication for Digital Payments directions (2025) |
| 4 | GST | Can a car dealer claim input tax credit on demo vehicles? | Cites Circular 231/25/2024-GST |
| 5 | GST | What is the place of supply for data hosting services given to cloud providers located outside India? | Cites Circular 232/26/2024-GST |
| 6 | GST | Is an e-invoice required for a supply to a government department registered only to deduct TDS? | Cites Circular 198/10/2023-GST |
| 7 | Both | A bank gives custodial services to foreign portfolio investors. What is the GST place of supply, and what KYC must the bank do? | Router picks both; cites Circular 220/14/2024-GST and the KYC Directions separately |
| 8 | Both | How does GST treat vouchers and prepaid instruments, and how does RBI regulate issuers of prepaid payment instruments? | Cites Circular 243/37/2024-GST and the PPI Master Direction |
| 9 | Superseded | Under the 2020 Priority Sector Lending Master Direction, what is the overall PSL target for a domestic commercial bank? | Answers from the 2025 PSL Direction and says clearly that the 2020 one was superseded |
| 10 | Abstain | What TDS rate applies to fixed deposit interest under the Income-tax Act? | Abstains: income tax is outside the corpus |

Why these types: they exercise the four behaviours we are graded on (routing, citation, supersession, abstention).

---

## 2. Amazon Bedrock: models, region, auth, prices

All model calls are plain on-demand `InvokeModel` / `Converse` calls on the `bedrock-runtime` endpoint. Nothing is created in AWS (no Knowledge Bases, no OpenSearch Serverless, no provisioned throughput). *Why:* a call that is not made costs nothing; an always-on resource bills every hour.

### 2.1 Models **[verified 2026-11-16]**

> **Model change, 2026-11-16 (decision 7).** AWS Support confirmed that Goutham's account is billed by AWS India (AISPL) and, under the RBI payment-aggregator rule, cannot subscribe to paid AWS Marketplace products with a card. Anthropic Claude and Cohere models on Bedrock need such a subscription, so v1 uses **Amazon's own (first-party) models only**, which need no Marketplace subscription. Claude and Cohere stay documented below as the **upgrade path**: once the account switches to "Pay By Invoice", changing the three model IDs in `.env` is enough. Wherever older text in this spec says "Haiku", read "the default LLM" (Nova 2 Lite); "Sonnet" means "the final-run judge" (Nova Pro); "Cohere" means "the reranker" (Amazon Rerank 1.0).

**v1 defaults (all Amazon first-party, no Marketplace):**

| Role | Model | ID to pass as `modelId` | How it is served |
|---|---|---|---|
| Embeddings | Amazon Titan Text Embeddings V2 | `amazon.titan-embed-text-v2:0` | In-region. No inference profile. |
| Reranker | Amazon Rerank 1.0 | `amazon.rerank-v1:0` | In-region only: Tokyo, Canada, Frankfurt, Oregon. **Not** in Mumbai, Hyderabad or us-east-1. |
| Router, answer, golden-set drafting, judge for development runs | Amazon Nova 2 Lite (launched 2025-12-02, newest Nova text model) | `global.amazon.nova-2-lite-v1:0` | **Inference profile required**: no in-region option in Tokyo. `jp.amazon.nova-2-lite-v1:0` also works (stays in Japan, about 10% dearer). |
| Judge for the final reported run only | Amazon Nova Pro | `apac.amazon.nova-pro-v1:0` | **Geo profile required** from Tokyo; Nova Pro has no `global.` profile. *Why a different model:* a stronger model than the one that wrote the answers is a fairer judge. |

**Upgrade path (needs Pay By Invoice on an AISPL account):**

| Role | Model | ID |
|---|---|---|
| Reranker | Cohere Rerank 3.5 | `cohere.rerank-v3-5:0` (in-region, Tokyo yes) |
| LLM | Claude Haiku 5.5 | `global.anthropic.claude-haiku-5-5` |
| Final judge | Claude Sonnet 5.5 | `global.anthropic.claude-sonnet-5-5` |

Sources:
- Titan V2: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-titan-text-embeddings-v2.html
- Reranker regions: https://docs.aws.amazon.com/bedrock/latest/userguide/rerank-supported.html
- Nova 2 Lite: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-lite.html
- Nova Pro: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-pro.html
- Cohere Rerank 3.5: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-cohere-rerank-3-5.html
- Claude Haiku 5.5: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-5-5.html
- Claude Sonnet 5.5: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html
- Model index: https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html

**What an inference profile is.** Instead of a model ID you pass a profile ID. Bedrock then picks a region with free capacity. The prefix says how far the request may travel:
- `global.` : any commercial region. Standard price.
- `us.`, `eu.`, `jp.`, `au.`, `ca.` : stays inside that geography. 10% more expensive.
- `apac.` : stays inside Asia-Pacific. Nova Pro offers only geo profiles, so from Tokyo it is `apac.`.

We use `global.` wherever it exists (Nova 2 Lite). *Why:* it is the cheapest, it works from every region, and our prompts contain only public documents, so there is no data-residency reason to pay 10% more.

Model facts that affect our code **[verified on the model card]**:
- Titan V2: 8K-token input, output size 256, 512 or 1024 numbers. Called with `InvokeModel` only (no Converse).
- Amazon Rerank 1.0: called with `InvokeModel` on `bedrock-runtime`, billed per *search unit* ($1 per 1,000). Exact request/response field names **[to verify in Task 11's live test]**.
- Nova 2 Lite: 1M context, 64K max output, supports `Converse` and `InvokeModel`. Reasoning is **off by default** (enabled only with `reasoningConfig`), so we pay no thinking tokens unless we turn it on. Count Tokens is not supported; token counts come from each response's `usage`. Its card says end of life is no sooner than 2026-12-02; if AWS announces a date, switch the ID in `.env`.
- Nova Pro: 300K context, 10K max output, `Converse` and `InvokeModel`.
- Cohere Rerank 3.5 (upgrade path): about 4K tokens per query+document pair. Called with `InvokeModel`.
- Haiku 5.5 (upgrade path): 1M context, supports `Converse` and `InvokeModel`. "Adaptive thinking" is on by default and thinking tokens are billed as output tokens. The Count Tokens API is **not** supported on `bedrock-runtime`, so we take token counts from the `usage` field of each response.
- Sonnet 5.5 (upgrade path): same APIs. Thinking is on by default at a higher effort than Haiku and cannot be fully switched off, so expect more output tokens per judge call. Count Tokens is not supported either.

### 2.2 Region

> **Region change, 2026-11-16 (decision 8).** Main region is now **`ap-south-1` (Mumbai)** for embeddings and LLM calls. Only the reranker is called in **`ap-northeast-1` (Tokyo)**, set by `BEDROCK_RERANK_REGION`, because no Indian region offers a Bedrock reranker. *Why:* Tokyo returned "AccessDeniedException: Your account is currently being verified" in both of Goutham's AWS accounts, while Mumbai worked in the console playground. Mumbai is also the closest region. One long-term Bedrock API key works in both regions (only short-term keys are tied to one region: https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html). Until Tokyo's verification clears, only the `hybrid_rerank` configuration is blocked. The text and table below are the original Tokyo analysis, kept for the record.

| Region | Titan V2 | Cohere Rerank 3.5 | Amazon Rerank 1.0 | Haiku 5.5 | All three? |
|---|---|---|---|---|---|
| ap-south-1 (Mumbai) | yes | **no** | **no** | `global.` only | **No** |
| ap-south-2 (Hyderabad) | yes | no | no | `global.` only | No |
| ap-northeast-1 (Tokyo) | yes | yes | yes | `global.` or `jp.` | **Yes** |
| us-east-1 (N. Virginia) | yes | yes | no | `global.` or `us.` | Yes |
| us-west-2 (Oregon) | yes | yes | yes | `global.` or `us.` | Yes |
| eu-central-1 (Frankfurt) | yes | yes | yes | `global.` or `eu.` | Yes |

**Decision (approved 2026-11-16): `ap-northeast-1` (Tokyo).**

- Mumbai does **not** qualify: neither reranker is offered there, and reranking is one of the four configurations we must evaluate.
- Among the regions that have everything, Tokyo is the nearest to Hyderabad, so the embedding and rerank calls (which always run in the region you call) have the shortest round trip. We make three Bedrock calls per question, so this adds up.
- Tokyo also has both rerankers, so we can swap Cohere for Amazon Rerank without changing region.
- Fallback: `us-east-1`. It is the region every AWS example uses. Changing region is one line in `.env` (`AWS_REGION`). Nothing else in the code may hard-code a region.

Not verified: actual latency numbers from Hyderabad, and the default request quotas a new account gets in Tokyo. Task 10 measures latency in its live test; if Tokyo quotas are too low we switch to `us-east-1`.

### 2.3 Authentication: two options

| | Option A: Bedrock API key | Option B: IAM user access keys |
|---|---|---|
| Env vars | `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` |
| What it can reach | Only Bedrock and Bedrock Runtime actions | Whatever the IAM policy allows (could be the whole account if set up carelessly) |
| Expiry | Long-term key: you pick an expiry (for example 30 days). Short-term key: 12 hours at most | Never expires unless you rotate it |
| Works with `bedrock-agent-runtime` `Rerank` API | **No** | Yes |
| Works with `InvokeModel` / `Converse` | Yes | Yes |
| Setup | Bedrock console, "API keys", one click. AWS creates an IAM user with the managed policy `AmazonBedrockLimitedAccess` | Create IAM user, attach policy below, create access key |

Sources **[verified]**: https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html , https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-reference.html , https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-supported.html (Tokyo and us-east-1 both support API keys; the Python SDK is supported).

**Recommendation for a solo developer: Option A, a long-term Bedrock API key with a 30-day expiry.**
*Why:* if the key ever leaks, it can only call Bedrock and it dies on its own. An IAM access key lives for ever and can be given far wider powers by mistake. AWS labels long-term API keys "for exploration", which is exactly what this project is.

**Consequence for the design:** because API keys cannot call the `bedrock-agent-runtime` `Rerank` API, the reranker is called through **`InvokeModel` on `bedrock-runtime`** with model ID `amazon.rerank-v1:0` (or `cohere.rerank-v3-5:0` on the upgrade path). This way the same code works with either auth option.

Rules for the code:
- `boto3` reads these variables from the process environment, not from `.env` by itself. `config.py` must call `load_dotenv()` before any boto3 client is created.
- Set **only one** option in `.env`. *Why:* with both set it is unclear to a beginner which one is in use.
- Never print, log or commit either value.

**Minimal IAM policy (Option B, or to tighten Option A).** Replace `ACCOUNT_ID`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeOnlyTheThreeModels",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:ap-northeast-1::foundation-model/amazon.titan-embed-text-v2:0",
        "arn:aws:bedrock:ap-northeast-1::foundation-model/amazon.rerank-v1:0",
        "arn:aws:bedrock:ap-northeast-1:ACCOUNT_ID:inference-profile/global.amazon.nova-2-lite-v1:0",
        "arn:aws:bedrock:*::foundation-model/amazon.nova-2-lite-v1:0",
        "arn:aws:bedrock:::foundation-model/amazon.nova-2-lite-v1:0",
        "arn:aws:bedrock:ap-northeast-1:ACCOUNT_ID:inference-profile/apac.amazon.nova-pro-v1:0",
        "arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0"
      ]
    }
  ]
}
```

- A global inference profile needs permission on the profile **and** on the underlying model in the regions it can route to; that is why the Nova lines use wildcard regions. The two Nova Pro lines are needed only for the final judge run (Task 28). On the upgrade path, add the matching Cohere and Claude ARNs the same way.
- With Option A the IAM user also needs `bedrock:CallWithBearerToken` (the default policy AWS attaches already allows API-key use).
- **[to verify]** The exact ARN forms above come from the general AWS pattern, not from a page fetched today. Task 04's live test confirms them.
- **[verified by AWS Support, 2026-11-16]** Cohere and Anthropic models need an AWS Marketplace subscription, which this AISPL account cannot buy by card (RBI payment-aggregator rule; fix: switch to Pay By Invoice). This is why v1 uses Amazon models only. Amazon models need no Marketplace step; do one test call to Nova 2 Lite from the Bedrock console playground in Tokyo before running any code.
- **Bedrock access is not confirmed yet.** The first live tests (Task 04) are what confirm that the account can call these models from Tokyo.

**Credits and the budget alarm.** Goutham has $100 of AWS promotional credits. Two things to do in the AWS console before the first live test:
1. **[verified by AWS Support, 2026-11-16]** The account has USD 113.38 of credits valid until 2027-06-12 (Free Tier USD 53.38 plus three Explore AWS credits of USD 20), and all of them list Amazon Bedrock as an applicable product. Amazon first-party models are ordinary Bedrock charges, so the credits cover them. Whether credits would cover Marketplace-billed models (the upgrade path) is still unanswered.
2. Create a monthly cost budget (for example $10) with an email alert, and in the budget's advanced options **untick "Credits"** so they are excluded. *Why:* with credits included, the budget shows $0 until the credits run out, so the alarm would never warn about real usage.

### 2.4 Prices (on-demand, USD) for cost logging

| Model | Price (region it is called in) | Status |
|---|---|---|
| Titan Text Embeddings V2 (Mumbai) | $0.024 per 1M input tokens | **[verified]** AWS Price List API, ap-south-1, 2026-11-16 |
| Amazon Rerank 1.0 (Tokyo) | $1.00 per 1,000 search units ($0.001 per unit). A search unit is one query of up to 100 documents **[definition to verify in Task 11]** | **[verified price]** AWS Price List API, Tokyo |
| Nova 2 Lite, `global.` profile (Mumbai) | $0.35 per 1M input, $2.95 per 1M output | **[verified]** AWS Price List API, ap-south-1 (`cross-region-global` rate) |
| Nova Pro (Mumbai) | $0.94 per 1M input, $3.76 per 1M output | **[verified]** AWS Price List API, ap-south-1 (rate for the `apac.` profile assumed equal; check the first bill) |
| *Upgrade path:* Cohere Rerank 3.5 | $2.00 per 1,000 queries | **[verified]** https://aws.amazon.com/bedrock/pricing/ |
| *Upgrade path:* Claude Haiku 5.5, `global.` | $0.10 per 1M input, $0.50 per 1M output | **[verified]** https://platform.claude.com/docs/en/about-claude/pricing |
| *Upgrade path:* Claude Sonnet 5.5, `global.` | $2 per 1M input, $10 per 1M output | **[verified]** same source |

Price source for the Amazon rows: the public AWS Price List files, `https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/<region>/index.json` for `ap-south-1` and `ap-northeast-1`. *Why that file:* the pricing web page renders its tables with JavaScript and could not be read.

Prices live in one file, `src/regrag/bedrock/pricing.py`, as a dictionary keyed by model ID, with a `PRICES_CHECKED_ON` date. *Why:* prices change; one place to update, and the log can say how old the numbers are.

**Rough budget.** Embedding the whole corpus (about 1.5M tokens): about $0.05. One question: rerank $0.001 + Nova 2 Lite about $0.002 (3K tokens in, 300 out) = roughly $0.003. One development evaluation (120 questions x 4 configurations, Nova 2 Lite as judge): under $3. The single final reported run with Nova Pro as judge (about 480 judged answers, about 4K tokens in and 300 out each): about $2.50. Everything together should stay well under $20, inside the free credits.

---

## 3. Corpus plan

Target: 25 RBI documents and 40 GST circulars. Only official sites. Every document gets a row in `data/manifest.csv` with source URL and publish date. PDFs go to `data/raw/` (gitignored).

### 3.1 Important background (verified today)

- **RBI reorganised its rulebook on 28 November 2025.** The old subject-wise Master Directions (for example the 2016 KYC Master Direction) were repealed and re-issued as separate Directions per type of entity (commercial banks, NBFCs, small finance banks, and so on). A second batch followed on 31 July 2026 (fraud, cyber security, audit). This is the biggest supersession event in the corpus and a good test of our supersession handling. Source: https://www.rbi.org.in/Scripts/BS_ViewMasterDirections.aspx
- **`cbic-gst.gov.in` no longer lists GST circulars.** Today its pages carry only excise/cess advisories; `central-tax-circulars.html` returns 404. It points to `taxinformation.cbic.gov.in`, which our fetch tool could not open (TLS certificate error). The official **GST Council** site lists the same CBIC circulars with PDFs and did load: https://gstcouncil.gov.in/cgst-circulars . It is the accepted GST source for v1 (decision 2, section 11).

### 3.2 RBI documents (25)

URL pattern: `https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=<ID>`. Each page links its PDF on `rbidocs.rbi.org.in`.

Status of this table: every ID and topic below was seen on the RBI Master Directions index on 2026-11-15. Only ID 13141 was opened individually. **Exact titles, reference numbers and PDF links are copied from each page by Task 05**; the topic names here are short labels, not official titles.

| # | ID | Topic (short label) | Applies to | Issued |
|---|---|---|---|---|
| 1 | 13141 | Know Your Customer | Commercial banks | 2025-11-28 |
| 2 | 13155 | Credit cards and debit cards: issuance and conduct | Commercial banks | 2025-11-28 |
| 3 | 13139 | Managing risks in outsourcing | Commercial banks | 2025-11-28 |
| 4 | 13140 | Responsible business conduct | Commercial banks | 2025-11-28 |
| 5 | 13149 | Interest rates on advances | Commercial banks | 2025-11-28 |
| 6 | 13157 | Interest rate on deposits | Commercial banks | 2025-11-28 |
| 7 | 13154 | Credit information reporting | Commercial banks | 2025-11-28 |
| 8 | 13163 | Digital banking channels authorisation | Commercial banks | 2025-11-28 |
| 9 | 13641 | Fraud risk management | Commercial banks | 2026-07-31 |
| 10 | 13642 | Digital payment security controls | Commercial banks | 2026-07-31 |
| 11 | 13643 | Cyber security and technology risk framework | Commercial banks | 2026-07-31 |
| 12 | 12943 | Know Your Customer | NBFCs | 2025-11-28 |
| 13 | 12965 | Registration, exemptions, scale-based regulation | NBFCs | 2025-11-28 |
| 14 | 12957 | Credit facilities | NBFCs | 2025-11-28 |
| 15 | 13591 | Digital payment security controls | NBFCs | 2026-07-31 |
| 16 | 12156 | Prepaid Payment Instruments | Payment systems | 2021-08-27 |
| 17 | 12896 | Regulation of payment aggregators | Payment systems | 2025-09-15 |
| 18 | 12898 | Authentication for digital payment transactions | Payment systems | 2025-09-25 |
| 19 | 13374 | E-mandate framework for digital payments | Payment systems | 2026-04-21 |
| 20 | 12616 | Bharat Bill Payment System | Payment systems | 2024-02-29 |
| 21 | 13752 | Domestic money transfer | Payment systems | 2026-11-11 |
| 22 | 13751 | Cyber resilience for non-bank payment system operators | Payment systems | 2026-11-05 |
| 23 | 10192 | Liberalised Remittance Scheme | FEMA | 2016 (updated 2024) |
| 24 | 12799 | Priority sector lending: targets and classification | Banks | 2025-03-24 |
| 25 | 11959 | Priority sector lending (2020), **superseded by #24** | Banks | 2020-09-04 |

Verified detail for #1: title "Reserve Bank of India (Commercial Banks – Know Your Customer) Directions, 2025", reference RBI/DOR/2025-26/169, PDF https://rbidocs.rbi.org.in/rdocs/notification/PDFs/169MD.PDF .

Optional historical documents, to add only if the URL can be confirmed in a browser **[to verify]**: the 2016 KYC Master Direction and the 2021 Master Direction on Digital Payment Security Controls. *Why they are useful:* they give us a superseded twin for documents #1 and #10, which makes better supersession test questions.

Why two KYC documents (banks and NBFCs): they are near-duplicates. They test whether retrieval and citations keep the right entity type, a realistic failure.

### 3.3 GST circulars (40)

Base URL: `https://gstcouncil.gov.in`. **[verified]** All 40 rows (number, date, PDF path) were read from https://gstcouncil.gov.in/cgst-circulars (pages 0 to 5) on 2026-11-15. Subjects are short labels.

| # | Circular | Date | Subject (short label) | PDF path |
|---|---|---|---|---|
| 1 | 250/07/2025-GST | 2025-06-24 | Review/appeal authorities for DGGI adjudication orders | /sites/default/files/2025-07/circular-no-250-2025_1.pdf |
| 2 | 249/06/2025-GST | 2025-06-09 | DIN on officer communications (modifies earlier DIN circular) | /sites/default/files/2025-07/circular-no-249-2025.pdf |
| 3 | 248/05/2025-GST | 2025-03-27 | Section 128A waiver scheme issues | /sites/default/files/2025-04/circular-no-248-05-2025.pdf |
| 4 | 246/03/2025-GST | 2025-01-30 | Late fee for delayed GSTR-9C | /sites/default/files/2025-01/cir-cgst-246-03-2025.pdf |
| 5 | 245/02/2025-GST | 2025-01-28 | GST applicability on certain services | /sites/default/files/2025-01/cir-245022025-cgst.pdf |
| 6 | 244/01/2025-GST | 2025-01-28 | Co-insurance premium and reinsurance commission | /sites/default/files/2025-01/cir-244012025-cgst.pdf |
| 7 | 243/37/2024-GST | 2024-12-31 | GST treatment of vouchers | /sites/default/files/2025-01/circular-no-243-2024.pdf |
| 8 | 242/36/2024-GST | 2024-12-31 | Place of supply: online services to unregistered recipients | /sites/default/files/2025-01/circular-no-242-2024.pdf |
| 9 | 241/35/2024-GST | 2024-12-31 | ITC on ex-works deliveries | /sites/default/files/2025-01/circular-no-241-2024.pdf |
| 10 | 240/34/2024-GST | 2024-12-31 | ITC of e-commerce operators, section 9(5) supplies | /sites/default/files/2025-01/circular-no-240-2024.pdf |
| 11 | 239/33/2024-GST | 2024-12-04 | Amends 2018 circular on proper officers (sections 73, 74) | /sites/default/files/2025-01/cir-cgst-239-2024.pdf |
| 12 | 238/32/2024-GST | 2024-10-15 | Section 128A doubts | /sites/default/files/2024-10/circular-no-238-2024.pdf |
| 13 | 237/31/2024-GST | 2024-10-15 | Section 16(5) and 16(6) ITC implementation | /sites/default/files/2024-10/circular-no-237-2024.pdf |
| 14 | Corrigendum to 237 | 2024-10-25 | Correction to Circular 237/31/2024 | /sites/default/files/2024-12/cir-cgst-corr-237-2024.pdf |
| 15 | 233/27/2024-GST | 2024-09-11 | IGST refunds and rule 96(10) | /sites/default/files/2024-10/cir-cgst-233-2024.pdf |
| 16 | 232/26/2024-GST | 2024-09-11 | Place of supply: data hosting for overseas cloud providers | /sites/default/files/2024-10/cir-cgst-232-2024.pdf |
| 17 | 231/25/2024-GST | 2024-09-11 | ITC on demo vehicles | /sites/default/files/2024-10/cir-cgst-231-2024.pdf |
| 18 | 230/24/2024-GST | 2024-09-11 | Advertising services to foreign clients | /sites/default/files/2024-10/cir-cgst-230-2024.pdf |
| 19 | 227/21/2024-GST | 2024-07-11 | Refund applications by Canteen Stores Department | /sites/default/files/2024-09/circular-no-227-2024.pdf |
| 20 | 226/20/2024-GST | 2024-07-11 | Refund of extra IGST after upward price revision of exports | /sites/default/files/2024-09/circular-no-226-2024.pdf |
| 21 | 225/19/2024-GST | 2024-07-11 | Corporate guarantees: valuation (further to 204) | /sites/default/files/2024-09/circular-no-225-2024.pdf |
| 22 | 224/18/2024-GST | 2024-07-11 | Recovery of dues before the Appellate Tribunal works | /sites/default/files/2024-09/circular-no-224-2024.pdf |
| 23 | 220/14/2024-GST | 2024-06-26 | Place of supply: custodial services to FPIs | /sites/default/files/2024-09/circular-no-220-14-2024.pdf |
| 24 | 219/13/2024-GST | 2024-06-26 | ITC on ducts and manholes of optical fibre networks | /sites/default/files/2024-09/circular-no-219-13-2024.pdf |
| 25 | 217/11/2024-GST | 2024-06-26 | ITC for insurers on motor repair claims | /sites/default/files/2024-09/circular-no-217-11-2024.pdf |
| 26 | 216/10/2024-GST | 2024-06-26 | Warranty: GST and ITC (**updates 195/07/2023**) | /sites/default/files/2024-09/circular-no-216-10-2024.pdf |
| 27 | 214/08/2024-GST | 2024-06-26 | ITC reversal, life insurance premium | /sites/default/files/2024-09/circular-no-214-08-2024.pdf |
| 28 | 212/06/2024-GST | 2024-06-26 | Evidence for post-sale discounts, section 15(3)(b)(ii) | /sites/default/files/2024-09/circular-no-212-06-2024.pdf |
| 29 | 211/05/2024-GST | 2024-06-26 | Section 16(4) time limit for reverse-charge ITC | /sites/default/files/2024-09/circular-no-211-05-2024.pdf |
| 30 | 210/04/2024-GST | 2024-06-26 | Valuation of imported services from related persons | /sites/default/files/2024-09/circular-no-210-04-2024.pdf |
| 31 | 209/03/2024-GST | 2024-06-26 | Place of supply, section 10(1)(ca) IGST Act | /sites/default/files/2024-09/circular-no-209-03-2024.pdf |
| 32 | 204/16/2023-GST | 2023-10-27 | Personal and corporate guarantees | /sites/default/files/2024-06/circular-no-204-16-2023.pdf |
| 33 | 203/15/2023-GST | 2023-10-27 | Place of supply in various cases | /sites/default/files/2024-06/circular-no-203-15-2023.pdf |
| 34 | 202/14/2023-GST | 2023-10-27 | Export of services, section 2(6)(iv) IGST Act | /sites/default/files/2024-06/circular-no-202-14-2023.pdf |
| 35 | 199/11/2023-GST | 2023-07-17 | Services between distinct offices of one organisation | /sites/default/files/2024-06/circular-cgst-199.pdf |
| 36 | 198/10/2023-GST | 2023-07-17 | E-invoicing issues | /sites/default/files/2024-06/circular-cgst-198.pdf |
| 37 | 197/09/2023-GST | 2023-07-17 | Refund-related issues | /sites/default/files/2024-06/circular-cgst-197.pdf |
| 38 | 195/07/2023-GST | 2023-07-17 | Warranty replacement: ITC (**updated by 216**) | /sites/default/files/2024-06/circular-cgst-195.pdf |
| 39 | 194/06/2023-GST | 2023-07-17 | TCS under section 52 with multiple e-commerce operators | /sites/default/files/2024-06/circular-cgst-194.pdf |
| 40 | 193/05/2023-GST | 2023-07-17 | ITC mismatch GSTR-3B vs GSTR-2A | /sites/default/files/2024-06/circular-cgst-193.pdf |

**Out of v1 (future work):** circulars numbered 251 and above (late 2025 and 2026). Secondary news sites mention circulars up to about 265/2026 (including one on omission of rule 96(10), which would affect row 15), but the GST Council list ended at 250 on 2026-11-15 and the CBIC site would not open. Because of this, answers from v1 may miss a 2026 change to one of these 40 circulars; the README says so under known limitations.

### 3.4 How supersession and amendment links are captured

Three sources, in order of trust:

1. **Hand-curated `data/relations.csv`** (committed). Columns: `from_doc_id, relation, to_doc_ref, to_doc_id, scope_note, evidence`. Seeded in Task 05 with the links already known from the tables above (RBI #24 supersedes #25; GST 216 amends 195; 225 clarifies 204; 239 amends a 2018 circular; 249 amends the earlier DIN circular; corrigendum corrects 237). *Why by hand first:* a wrong "superseded" flag is worse than a missing one, and a small trusted list gives the tests something solid.
2. **Text extraction at ingest** (Task 09). Regular expressions look for phrases such as "supersedes", "in supersession of", "stands withdrawn", "withdrawn ab initio", "is hereby repealed", "amended as under", "corrigendum", "in partial modification of", and capture the circular or direction number that follows. Each hit is stored with the exact sentence as evidence and `source = 'extracted'`.
   - RBI new-style Directions end with a chapter "Repeal and Other Provisions". **[verified on #1]** That chapter does not list the old circulars; it points to one repeal circular dated 2025-11-28. So for RBI we record "this Direction repeals earlier KYC instructions for commercial banks" as a relation whose target is a text reference, not a document in our corpus.
   - Older RBI Master Directions (for example PPI, #16) carry an appendix listing the circulars they consolidated. Each listed circular becomes a `supersedes` relation with `to_doc_id` empty (the old circular is not in our corpus) and `to_doc_ref` holding its number.
   - RBI "Updated as on <date>" in a title is stored in `documents.updated_as_on`. We ingest only the current version in v1.
3. **`status` column in the manifest**: `active`, `superseded`, `withdrawn`. A document is `superseded` only when a relation in source 1 says so. Extracted relations (source 2) never change status automatically; they produce a flag for review. *Why:* "amended" usually changes one paragraph, not the whole document.

Relations whose target is not in the corpus are still kept. *Why:* if a user asks about an old circular by number, we can say "that circular was consolidated into X" even though we never ingested it.

---

## 4. Data model (Postgres 17 + pgvector, in Docker)

Image `pgvector/pgvector:pg17`, published on host port **5433**. *Why 5433:* avoids clashing with any Postgres already on 5432.

### `documents`
| Column | Type | Notes |
|---|---|---|
| `doc_id` | text, primary key | Stable slug, e.g. `rbi-13141`, `gst-231-25-2024`. Used in citations and the golden set. |
| `corpus` | text, not null | `rbi` or `gst` (check constraint) |
| `doc_type` | text | `master_direction`, `direction`, `circular`, `corrigendum` |
| `title` | text, not null | Official title |
| `reference_no` | text | e.g. `RBI/DOR/2025-26/169`, `231/25/2024-GST` |
| `applies_to` | text | e.g. `commercial_banks`, `nbfc`; empty for GST |
| `publish_date` | date, not null | |
| `updated_as_on` | date | RBI only |
| `source_url` | text, not null | Page where it is listed |
| `pdf_url` | text, not null | Direct PDF link |
| `sha256` | text | Of the downloaded PDF. *Why:* tells us if the regulator silently replaced the file |
| `page_count` | int | |
| `status` | text, not null, default `active` | `active`, `superseded`, `withdrawn` |
| `ingested_at` | timestamptz | |

### `chunks`
| Column | Type | Notes |
|---|---|---|
| `chunk_id` | bigint identity, primary key | |
| `doc_id` | text, foreign key to documents, on delete cascade | |
| `chunk_index` | int | Order within the document; unique with `doc_id` |
| `section_no` | text | e.g. `Chapter VI, para 16`, `Para 3.2` |
| `section_path` | text | Heading trail, e.g. `Chapter VI > Customer Due Diligence > Part I` |
| `page_start`, `page_end` | int | 1-based PDF pages |
| `content_type` | text | `text` or `table` |
| `content` | text, not null | Tables are stored as Markdown tables |
| `token_count` | int | Estimate (characters / 4) |
| `embedding` | vector(1024) | Titan V2 output |
| `embedding_model` | text | *Why:* if we change model, we know which rows are stale |
| `tsv` | tsvector, generated always as `to_tsvector('english', coalesce(section_path,'') || ' ' || content)` stored | Keyword search |

### `document_relations`
`relation_id` (identity PK), `from_doc_id` (FK), `relation` (`supersedes`, `amends`, `withdraws`, `clarifies`, `corrects`), `to_doc_ref` (text, always filled), `to_doc_id` (FK, nullable), `scope_note` (text, e.g. "para 4 only"), `evidence` (text, the sentence), `source` (`manual` or `extracted`), `reviewed` (bool).

### `query_logs`
`query_id` (uuid PK), `created_at`, `question`, `route`, `config_name`, `retrieved_chunk_ids` (bigint[]), `reranked_chunk_ids` (bigint[]), `rerank_top_score` (real), `abstained` (bool), `abstain_reason` (text), `answer` (text), `citations` (jsonb), `latency_ms` (jsonb, per stage), `input_tokens`, `output_tokens`, `embed_tokens`, `rerank_queries` (ints), `cost_usd` (numeric(10,6)), `model_ids` (jsonb).

### Indexes
- `chunks`: HNSW on `embedding vector_cosine_ops` (defaults m=16, ef_construction=64). *Why HNSW:* good recall with no tuning, and unlike IVFFlat it does not need the data loaded first. *Why cosine:* Titan vectors are normalised, and cosine is the usual choice for text.
- `chunks`: GIN on `tsv`. *Why:* makes keyword search fast.
- `chunks (doc_id)`; `documents (corpus, status)`; `document_relations (to_doc_id)`, `(from_doc_id)`; `query_logs (created_at)`.

The schema is one file, `src/regrag/db/schema.sql`, written so it can be run repeatedly (`create ... if not exists`). *Why no migration tool:* one developer, one database, v1. A migration tool is a non-goal.

---

## 5. Pipeline stages

Package name: `regrag` (in `src/regrag/`). Every number below is a **starting value** in `config.py`; Task 28 tunes them on the golden set.

### Ingestion

| Stage | Input | Output | Key parameters (start value: why) |
|---|---|---|---|
| **Manifest** | `data/manifest.csv`, `data/relations.csv` | Validated list of documents | Required columns: `doc_id, corpus, doc_type, title, reference_no, applies_to, publish_date, updated_as_on, source_url, pdf_url, status, sha256`. Loader rejects unknown hosts (only `rbi.org.in`, `rbidocs.rbi.org.in`, `gstcouncil.gov.in`, `cbic-gst.gov.in`, `taxinformation.cbic.gov.in`, `cbic.gov.in`): enforces the "official sources only" rule in code |
| **Download** | Manifest rows | `data/raw/<doc_id>.pdf`, sha256 written back | Delay 2 s between requests: be polite to government servers. Timeout 60 s, 3 retries. Skip if file exists with same sha256. TLS verification always on; if a site fails, the task reports it and the PDF can be saved by hand |
| **Parse** | PDF | List of pages, each with text blocks and tables | Library `pdfplumber`: extracts tables as rows/cells and has a permissive licence. Tables become Markdown. Repeated headers/footers and page numbers are stripped. A page with almost no text is reported as "scanned" and skipped (OCR is a non-goal) |
| **Chunk** | Parsed pages | Chunks with `section_no`, `section_path`, pages | Split first on headings (Chapter, Part, "Para 3.", "3.1", "Annex"); then pack to **target 400 tokens, hard max 500, overlap 60 tokens** inside a section: 400 keeps one rule per chunk and fits well inside the reranker's 4K limit; overlap stops a sentence that straddles a boundary being lost. A table is never split unless over 1,000 tokens, and it repeats its header row when split. Each chunk's text is prefixed with `title + section_path` before embedding: a bare paragraph like "The limit shall be Rs. 10,000" is meaningless without knowing which document it is from |
| **Supersession extract** | Chunks | Rows for `document_relations` | Regex list from section 3.4 |
| **Embed** | Chunk text | 1024-number vector | `dimensions=1024, normalize=true`: best quality, and 1024 is well inside pgvector's index limit. One call per chunk (Titan takes one text per call); max 4 concurrent calls; retry with backoff on throttling |
| **Store** | Documents, chunks, relations | Rows in Postgres | Upsert by `doc_id`: re-ingesting a document deletes and replaces its chunks in one transaction, so a failed run cannot leave half a document |

### Query

| Stage | Input | Output | Key parameters (start value: why) |
|---|---|---|---|
| **Router** | Question | `rbi`, `gst` or `both` | Step 1, keyword rules (e.g. "ITC", "GSTR", "place of supply" → gst; "KYC", "NBFC", "PPI" → rbi). Step 2, if rules are silent or hit both sides, ask Haiku to choose one word. Unsure → `both`: searching too widely costs a little accuracy; searching the wrong corpus loses the answer |
| **Keyword retrieve ("BM25")** | Question, route | Top 30 chunks | Postgres full-text search, `websearch_to_tsquery` + `ts_rank_cd`. **Honest note:** this is Postgres's ranking, which is similar in spirit to BM25 but not the exact formula. The config name stays `bm25` (short, and matches the target architecture), but every results table and the README label it **"keyword (Postgres FTS, BM25-like)"**. True BM25 is a non-goal for v1 |
| **Vector retrieve** | Question embedding, route | Top 30 chunks | Cosine distance on the HNSW index; `hnsw.ef_search = 100`: higher than the default 40 so filtered searches still return 30 rows |
| **Fuse (RRF)** | Two ranked lists | Top 30 fused | Reciprocal Rank Fusion, `score = sum(1 / (k + rank))`, **k = 60**: the value from the original RRF paper; it uses ranks, not raw scores, so the two very different scoring scales need no calibration |
| **Rerank** | Question + 30 chunks | Top 8 with scores 0 to 1 | Amazon Rerank 1.0 via `InvokeModel` (Cohere Rerank 3.5 on the upgrade path). 30 documents = 1 billed search unit ($0.001). **top_n = 8**: enough context for multi-part questions, small enough to keep the prompt cheap. Request and response field names for each reranker **[to verify in Task 11's live test]**; the code keeps one small adapter per reranker model |
| **Supersession filter/flag** | 8 chunks | Chunks annotated; some replaced | If a chunk's document has status `superseded`/`withdrawn` **and** the superseding document is in the corpus: keep at most one such chunk, mark it `SUPERSEDED BY <doc>`, and make sure at least the top chunk of the newer document is present. If the document is only `amended`: keep it and attach the amending reference. Never silently drop: the user may be asking about the old rule on purpose |
| **Generate** | Question + annotated chunks | Answer text with citation markers | Nova 2 Lite via `Converse` (reasoning off), `maxTokens = 1500`. Each chunk is shown as `[C1] doc title | section | pages`. The model must put `[C#]` after every claim and must reply `INSUFFICIENT_EVIDENCE` if the chunks do not answer the question. Send `maxTokens` and `temperature = 0` in `inferenceConfig` (Nova accepts both; a low temperature keeps answers repeatable for evaluation) |
| **Validate** | Answer + chunks | Final answer or abstention | (a) Every `[C#]` must match a supplied chunk; an unknown marker fails validation. (b) Every sentence that states a rule must carry a citation. (c) **Abstain if top rerank score < 0.30**, or the model said `INSUFFICIENT_EVIDENCE`, or (a) fails after one retry. 0.30 is a guess; Task 28 picks the value that best separates answerable from unanswerable golden questions |
| **Log** | Everything above | One `query_logs` row + one JSON line on stdout | Latency per stage, tokens, cost from `pricing.py`, chunk IDs |

Final answer shape (`QueryResult`): `answer`, `abstained`, `abstain_reason`, `citations` (list of `{marker, doc_id, title, section_no, page_start, page_end, source_url, status}`), `supersession_notes`, `route`, `usage`, `cost_usd`, `query_id`.

---

## 6. Evaluation plan

### 6.1 Golden set format

File `data/golden/golden.jsonl`, one JSON object per line. **This schema is stable**: later projects depend on it. New fields may be added; existing ones are never renamed or removed. `schema_version` is `1`.

```json
{
  "id": "g001",
  "schema_version": 1,
  "question": "Can a car dealer claim input tax credit on demo vehicles?",
  "corpus": "gst",
  "type": "factual",
  "expected_doc_ids": ["gst-231-25-2024"],
  "expected_sections": [{"doc_id": "gst-231-25-2024", "section_no": "Para 3", "page": 2}],
  "reference_answer": "Short correct answer written by a human.",
  "should_abstain": false,
  "must_flag_supersession": false,
  "tags": ["itc"],
  "source": "manual",
  "reviewed": true
}
```

- `corpus`: `rbi`, `gst`, `both`, or `none` (for out-of-corpus questions).
- `type`: `factual`, `table`, `cross_corpus`, `superseded`, `abstain`.
- `source`: `manual` or `llm_drafted`. `reviewed` must be `true` before a row counts in results.

### 6.2 Building ~120 questions

| Type | Count | How |
|---|---|---|
| factual, RBI | 35 | The default LLM (Nova 2 Lite) drafts 3 questions per sampled chunk; Goutham keeps the good ones and fixes the reference answer |
| factual, GST | 35 | Same |
| table lookups | 10 | Hand-picked chunks with `content_type = table` |
| cross_corpus | 10 | Hand-written |
| superseded | 15 | Hand-written from `data/relations.csv` |
| abstain | 15 | Hand-written: out-of-corpus (income tax, SEBI), and in-domain questions whose answer is not in our 65 documents |

Task 23 seeds 20 hand-written rows; Task 27 grows it to ~120. *Why a human reviews every row:* a golden set with wrong answers measures nothing.

**Fallback if review time runs short: 60 reviewed questions**, exactly half of each row above (18 RBI, 18 GST, 5 table, 5 cross-corpus, 7 superseded, 7 abstain). *Why keep the mix:* the superseded and abstain questions are the ones that test what makes this project different; cutting only those would hide its weak spots. The results table always states the actual number of questions used.

### 6.3 Metrics (exact definitions)

Retrieval metrics use only questions with `should_abstain = false`. A retrieved chunk is **relevant** if its `(doc_id, section_no)` matches an entry in `expected_sections`; if a question has no `expected_sections`, matching `doc_id` in `expected_doc_ids` is enough.

- **Recall@k** (k = 5 and 10): per question, 1 if at least one relevant chunk is in the top k, else 0. Report the mean. (This is "hit rate"; we use it because most questions have one gold section.)
- **MRR**: per question, 1 / rank of the first relevant chunk in the top 10, or 0 if none. Report the mean.
- **Citation validity**: of all citation markers in all non-abstained answers, the fraction that point to a chunk that was actually given to the model. Target 100%; the validator enforces it.
- **Citation accuracy**: of all cited chunks in non-abstained answers, the fraction whose `doc_id` is in the question's `expected_doc_ids`.
- **Faithfulness** (LLM judge): for each non-abstained answer, the judge gets the answer and the cited chunks and labels each sentence `supported` or `unsupported`. Score = supported / total sentences; report the mean. Judge model is set by `BEDROCK_JUDGE_MODEL_ID`: **Nova 2 Lite for development runs** (the default), **Nova Pro for the one final reported run** in Task 28 (Claude Sonnet 5.5 on the upgrade path). *Why two:* a model judging its own answers is cheap but can be lenient, so the number we publish comes from a stronger, different model. The results file records which judge was used.
- **Abstention correctness**: over all questions, the fraction where `abstained == should_abstain`. Also report abstention precision and recall. *Why both:* a system that abstains on everything gets perfect recall and is useless.
- **Supersession flag rate**: for `must_flag_supersession = true` questions, the fraction of answers with a non-empty `supersession_notes`.
- Also per run: mean and p95 latency, mean cost per question.

### 6.4 Configurations compared

| Config name | Label shown in results and README | Keyword | Vector | RRF | Rerank |
|---|---|---|---|---|---|
| `bm25` | keyword (Postgres FTS, BM25-like) | yes | | | |
| `vector` | vector (Titan V2) | | yes | | |
| `hybrid` | hybrid (keyword + vector, RRF) | yes | yes | yes | |
| `hybrid_rerank` | hybrid + rerank (Amazon Rerank 1.0) | yes | yes | yes | yes |

Router, supersession step, generator and validator are identical in all four. *Why:* only one thing changes per comparison, so differences are caused by retrieval. In configurations without a reranker the abstain rule uses only the model's `INSUFFICIENT_EVIDENCE` signal.

Output: `docs/eval/results.md` (table) and `docs/eval/results.json` (raw), committed. `--retrieval-only` runs recall and MRR without any LLM calls, which is nearly free.

---

## 7. Interfaces (the contract between tasks)

Defined once in `src/regrag/interfaces.py` as `typing.Protocol` classes, with plain dataclasses in `src/regrag/types.py`. *Why Protocols:* the fusion code can be written and tested against a fake retriever before the real one exists, and later projects can swap a part without touching the others.

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> EmbedResult: ...            # vectors + token count

class Retriever(Protocol):
    def retrieve(self, query: str, route: Route, top_k: int) -> list[RetrievedChunk]: ...

class Reranker(Protocol):
    def rerank(self, query: str, chunks: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]: ...

class Router(Protocol):
    def route(self, question: str) -> Route: ...                     # "rbi" | "gst" | "both"

class Generator(Protocol):
    def generate(self, question: str, chunks: list[RetrievedChunk]) -> DraftAnswer: ...

class Validator(Protocol):
    def validate(self, question: str, draft: DraftAnswer, chunks: list[RetrievedChunk]) -> ValidationResult: ...
```

**Single entry point:** `regrag.query.pipeline.answer_question(question: str, *, config: PipelineConfig | None = None) -> QueryResult`. The CLI, the eval harness and every future project call this one function. `PipelineConfig` selects the retrieval configuration and can carry replacement parts (a different reranker, extra validators).

---

## 8. Repository layout

```
docker-compose.yml
pyproject.toml  .env.example  README.md
data/manifest.csv  data/relations.csv  data/golden/golden.jsonl  data/raw/ (gitignored)
docs/SPEC.md  docs/TASKS.md  docs/CHANGELOG.md  docs/changelogs/  docs/eval/
src/regrag/
  config.py  types.py  interfaces.py
  bedrock/   client.py  pricing.py  embedder.py  reranker.py  llm.py
  db/        schema.sql  connection.py  init.py  repository.py
  ingest/    manifest.py  download.py  parse.py  chunk.py  supersession.py  pipeline.py
  retrieval/ keyword.py  vector.py  fusion.py  hybrid.py
  query/     router.py  supersession.py  prompts.py  generate.py  validate.py  querylog.py  pipeline.py
  eval/      golden.py  metrics.py  judge.py  draft_questions.py  run.py
tests/
```

Each runnable stage has its own entry point (`uv run python -m regrag.ingest.pipeline`, `-m regrag.query.pipeline "question"`, `-m regrag.eval.run`). *Why no single shared `cli.py`:* a shared file would force tasks to run one after another.

---

## 9. Non-goals for v1

- No HTTP API. Command line only in v1; a small Streamlit web page was added after v1 (Task 30, agreed with the owner 2026-11-16).
- No OCR for scanned PDFs; no Hindi or bilingual documents.
- No GST notifications, rate schedules, Acts or Rules; circulars only. No RBI FAQs or press releases.
- No GST circulars numbered 251 or above (late 2025 and 2026). Follow-up: add them once an official listing is confirmed.
- No automatic watching of RBI/CBIC sites for new documents. Re-running ingest is manual.
- No ingestion of previous versions of RBI Directions ("Updated as on" history).
- No true BM25 engine, no query rewriting, no multi-turn chat memory.
- No migration tool, no deployment, no CI pipeline, no authentication for end users.
- No always-on AWS resources of any kind.
- The five projects in section 10 are not built here; only their plug-in points are.

---

## 10. Extension points

| Future project | Where it plugs in | What v1 must provide |
|---|---|---|
| **Agent orchestration** | Calls `answer_question()` as a tool; may also call a `Retriever` directly | One entry point returning a typed `QueryResult`; no printing or global state inside the pipeline |
| **Semantic cache** | Wraps `answer_question()`: look up the question embedding first, return the stored `QueryResult` on a hit | `QueryResult` is serialisable to JSON; `Embedder` is reusable; `query_logs` records `config_name` and model IDs so a cache key can include them |
| **Guardrails / output validation** | Extra objects implementing `Validator`, run after the built-in one | `PipelineConfig.validators` is a list run in order; any validator can force abstention with a reason |
| **Eval dataset classification** | Reads and appends to `data/golden/golden.jsonl` | Stable schema with `schema_version`, `type`, `tags`, `source`, `reviewed`; loader ignores unknown extra fields |
| **LoRA fine-tuning** | Exports training pairs from `query_logs` + golden set; a fine-tuned model is used by writing a new `Generator` (or `Reranker`) | `query_logs` stores question, chunk IDs, answer and citations; `Generator` protocol hides which model answers |

Rule for all code: pipeline stages receive their collaborators as arguments (dependency injection) and never construct a Bedrock client or database connection inside a function body. *Why:* that is what makes mocking in tests, and swapping in later projects, possible.

---

## 11. Decisions (approved 2026-11-16)

1. **Region (amended by decision 8): originally `ap-northeast-1` (Tokyo); fallback `us-east-1`.** *Why:* Mumbai has no reranker, and Tokyo is the nearest region where embeddings, reranker and Claude all work on-demand.
2. **GST source: `gstcouncil.gov.in` is the official source for v1. Circulars 251 and above stay out of v1.** *Why:* it is a government site that lists the CBIC circulars with PDFs, while `cbic-gst.gov.in` no longer does; the newer circulars could not be confirmed on any official page, and we do not invent URLs.
3. **AWS account: $100 of promotional credits; Bedrock access not yet confirmed.** Check in Billing → Credits whether the credits cover Claude and Cohere (Marketplace-billed), and create the budget alarm with "Credits" excluded (section 2.3). Task 04's live test confirms access. *Why:* credits may not cover Marketplace models, and a budget that counts credits stays at $0 and never warns.
4. **Faithfulness judge (amended by decision 7): Nova 2 Lite for development runs, Nova Pro (`apac.amazon.nova-pro-v1:0`) for the final reported run in Task 28, about $2.50.** Originally Claude Haiku / Sonnet 5.5. *Why:* a stronger, different model is a fairer judge of Haiku's answers, but it is 20 times the price, so we pay for it once.
5. **Keyword leg: Postgres full-text search is accepted as the "BM25" leg.** Config name stays `bm25`; results and README label it "keyword (Postgres FTS, BM25-like)". *Why:* it needs no extra software, and the honest label avoids claiming an algorithm we do not run.
6. **Golden set: target about 120 reviewed questions; fallback 60 if review time runs short** (mix in section 6.2). *Why:* 120 gives steadier numbers, but 60 well-reviewed questions are worth more than 120 unchecked ones.
7. **Models: Amazon first-party only for v1 (approved 2026-11-16).** Titan V2 embeddings, Amazon Rerank 1.0, Nova 2 Lite (`global.amazon.nova-2-lite-v1:0`) as the LLM, Nova Pro as the final judge. Region stays Tokyo, the only nearby region with Amazon Rerank. *Why:* AWS Support confirmed that the AISPL account cannot subscribe to Marketplace models (Claude, Cohere) by card. Amazon models need no Marketplace step and are covered by the account's credits. Claude and Cohere remain a one-line `.env` upgrade after a switch to Pay By Invoice, which the Protocols from Task 02 make possible without code changes.
8. **Regions: `ap-south-1` (Mumbai) for embeddings and LLMs, `ap-northeast-1` (Tokyo) for the reranker only (approved 2026-11-16).** *Why:* Tokyo was under an AWS account-verification hold in both accounts while Mumbai worked; Mumbai is closest to Hyderabad; no Indian region has a Bedrock reranker. The client keeps one cached connection per region, and one long-term API key serves both.

Still to confirm during the build (not blocking): the items marked **[to verify]** in sections 2.3, 2.4 and 5. Each names the task that checks it.

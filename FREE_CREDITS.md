# Third-party credits and free tiers

**Deployment.inc does not provide candidate API or GPU credits, grants, reimbursements or sponsored
accounts.** Candidates cover their own development and submission costs. The US$50 submission limit
is a usage ceiling at pinned list prices, not a payment or credit from Deployment.inc.

The optional resources below are offered by their respective providers, independently of
Deployment.inc. Official sources were checked on **7 September 2026**, except where a verification
limit is stated. Providers control eligibility, availability, expiry, payment requirements and
charges beyond the allowance. Check your own account before relying on an offer.

## Speech APIs

| Provider | Provider's offer | Conditions and official source |
|---|---|---|
| **Deepgram** | **US$200 signup credit**; pricing page says no credit card required | For a new Deepgram account, not a Deployment.inc grant. [Pricing](https://deepgram.com/pricing). The pricing page uses no-expiration wording, but [billing documentation](https://developers.deepgram.com/guides/deep-dives/managing-projects) says promotional credits expire **one year from signup**. Plan around that limit and confirm it in your account. |

Deepgram is a general speech-development resource; none of the current six challenges requires it.
Its credits do not pay for another provider's LLM API or replace a required model snapshot.

## Compute

| Provider | Offer or resource | Conditions and official source |
|---|---|---|
| **Modal** | **US$30/month included compute** on Starter | A payment method is required; additional use is billed. [Pricing](https://modal.com/pricing), [billing requirements](https://modal.com/docs/guide/billing). |
| **Google Colab** | Free notebook compute, with variable accelerator availability | No guaranteed GPU type, runtime length or capacity; unsuitable as a guaranteed timed-test resource. [Official FAQ](https://research.google.com/colaboratory/faq.html). |
| **Kaggle Notebooks** | Notebook/GPU resource reference | [Official notebook docs](https://www.kaggle.com/docs/notebooks) and [GPU usage guide](https://www.kaggle.com/docs/efficient-gpu-usage). The docs did not render fully in this check; verify the current account quota rather than relying on an old GPU-hour or hardware figure. |
| **Hugging Face Spaces** | Static Spaces are free; CPU Basic has no hourly hardware charge | The current docs say creating a Gradio/Docker compute Space requires a paid plan. Do not treat this as universally free application hosting. Use private visibility for submission work; protected Spaces still expose the running app. [Hardware and visibility docs](https://huggingface.co/docs/hub/spaces-overview). |

No challenge requires a GPU. Hosted compute is optional and is reported separately from the API ceiling.

## LLM APIs

| Provider | Provider's offer | Conditions and official source |
|---|---|---|
| **Google Gemini API / AI Studio** | Free tiers for selected models | Availability is model-specific; some models have no free tier. The pricing table also distinguishes free-tier data use. [Official pricing](https://ai.google.dev/gemini-api/docs/pricing). |
| **Groq** | Free plan with model-specific rate limits | Check requests and token limits for the exact model. [Official limits](https://console.groq.com/docs/rate-limits). |
| **OpenRouter** | Free model variants | Availability and request limits apply; choose an eligible model rather than assuming any API call is free. [FAQ](https://openrouter.ai/docs/faq), [limits](https://openrouter.ai/docs/api-reference/limits). |
| **Cerebras** | **US$5 in trial credits** after creating an account | Provider trial, subject to account eligibility and current terms. [Official pricing](https://www.cerebras.ai/pricing). |

These are optional resources, not blanket approval to use a model. Check [MODELS.md](MODELS.md) and
the problem's restrictions: free access does not override pinned snapshots or the allowed model class.

## Evaluation, observability, embeddings and vector storage

| Provider | Provider's offer or resource | Official source |
|---|---|---|
| **Langfuse** | Free Hobby plan, 50,000 units/month; no card required | [Pricing](https://langfuse.com/pricing) |
| **Braintrust** | Free Starter plan includes US$10/month in model credits; no card required | [Pricing](https://www.braintrust.dev/pricing). Credits apply to Braintrust's supported model/AI features, not an arbitrary external API balance. |
| **Weights & Biases Weave** | Free-tier resource; check current plan limits | [Official project](https://github.com/wandb/weave), [pricing](https://wandb.ai/site/pricing/). The previous 5 GB/month claim is not carried forward. |
| **Helicone** | Free Hobby plan includes 10,000 requests/month | [Pricing](https://www.helicone.ai/pricing) |
| **Pinecone** | Free Starter plan with usage limits | [Pricing](https://www.pinecone.io/pricing/) |
| **Qdrant Cloud** | Free single-node tier: 1 GB RAM, 4 GB disk | [Pricing](https://qdrant.tech/pricing/) |
| **Weaviate Cloud** | Free shared tier, up to 100,000 objects and one collection | [Pricing](https://weaviate.io/pricing) |
| **Voyage AI** | Model-specific free token allowances; the listed Voyage 4 embedding models have 200 million free tokens | [Pricing](https://docs.voyageai.com/docs/pricing). Other models have different allowances; check the exact row. |

Keep hosted code, datasets, traces, dashboards and demos private. Verify access controls and provider
data terms before uploading private submission material. A tool appearing here does not relax the
private-submission rules or imply that its free plan provides every required feature.

## Cost reporting

Free usage still counts at the applicable pinned list price in the submitted API budget, including
failed runs, embeddings and reranking. Credits change the amount you pay, not the benchmark cost
reported. Compute is reported separately. See [README.md](README.md) and [MODELS.md](MODELS.md).

Official reviewer runs use Deployment.inc's evaluation infrastructure. They do not create an
entitlement to candidate credits, repayment of development costs or reimbursement of submission spend.

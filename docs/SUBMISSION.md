# Submission guide

## 1. Get a free AI key (5 min)
1. Go to https://aistudio.google.com/apikey and sign in with a Google account.
2. **Create API key**. No credit card is needed for the free tier.
3. Copy `.env.example` to `.env` and paste the key after `GEMINI_API_KEY=`.
4. Run `streamlit run app.py`. The sidebar should say **AI connected**.
5. Run `python eval.py --pause 4 --out results/eval_ai.md` and put the score into the README and video.
   The pause keeps you under free-tier rate limits.

## 2. Push to GitHub (5 min)
```bash
gh repo create node-solutions-triage-assistant --public --source=. --push
```
Or create an empty repo on github.com, then `git remote add origin <url> && git push -u origin main`.
Check that `.env` is **not** in the repo (it's git-ignored).

## 3. Deploy on Streamlit Community Cloud (10 min, free)
1. Go to https://share.streamlit.io and sign in with GitHub.
2. **Create app** → pick the repo, branch `main`, main file `app.py`.
3. **Advanced settings** → Python 3.12 → **Secrets**:
   ```toml
   GEMINI_API_KEY = "your-key"
   ```
4. Deploy. Open the URL in an **incognito window** to confirm it works without being logged in.
5. Paste the URL into the README (`Live app:` line) and push.

## 4. Record the video
Follow `docs/VIDEO_SCRIPT.md`. Upload to YouTube as **Unlisted** or share a Loom link with "anyone with the link can view".

## 5. Final checks (in an incognito window)
- [ ] Live app opens and triages request 05
- [ ] GitHub repo is public and the README renders
- [ ] Video link plays without sign-in
- [ ] No API key committed (`git log -p | grep -i "AIza"` returns nothing)

## 6. Reply to the challenge email

> **Subject:** Re: Node Solutions: AI Request Triage Assistant (Stage Two)
>
> Hi [Name],
>
> Thank you for the challenge. Please find my submission below:
>
> - **Video walkthrough (≈7 min):** [link]
> - **Live app:** [Streamlit link] (works without login)
> - **Repository:** [GitHub link], with setup steps, prompt design, decisions, limitations and next steps in the README
>
> **In short:** a Streamlit app that sends each request through one LLM call with a written triage rubric. It validates the structured output, falls back to keyword rules if the AI is unavailable, and applies safety guardrails, so data-exposure and outage cases are never under-prioritised. Every request gets a summary, category, priority with reason, owner and an editable draft reply. An inbox view sorts everything by urgency. I tested it on the six mock requests plus nine edge cases (prompt injection, a non-English message, vague and multi-issue requests).
>
> Happy to walk through any part of it.
>
> Best regards,
> [Your Name]

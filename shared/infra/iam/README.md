# IAM policies

Replace the placeholders before use: `<ACCOUNT_ID>`, `<REGION>`, `<REPORTS_BUCKET>`, `<VECTOR_BUCKET>`, `<GITHUB_USER>`. Do not commit the filled-in versions.

| File | Attach to | Grants |
|---|---|---|
| `crash-learner-policy.json` | your learning IAM user | create/seed/delete the QA table, reports bucket and vector index; Titan embeddings |
| `mcp-readonly-policy.json` | whatever runs the MCP server (an agent runtime, the CI eval role) | read-only: query runs, read `runs/*` reports, search the KB |
| `github-oidc-eval-trust.json` | trust policy of the CI eval role | lets GitHub Actions on `main` of this repo assume the role, with no stored keys |

## CI eval role (OIDC)

```bash
# once per account: register GitHub as an identity provider
aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com

aws iam create-role --role-name agentic-portfolio-evals \
  --assume-role-policy-document file://github-oidc-eval-trust.filled.json
aws iam put-role-policy --role-name agentic-portfolio-evals --policy-name mcp-readonly \
  --policy-document file://mcp-readonly-policy.filled.json
```

Then in the GitHub repo settings: variable `AWS_EVAL_ROLE_ARN` (the role ARN), variables `QA_REPORTS_BUCKET` and `QA_VECTOR_BUCKET`, and secret `ANTHROPIC_API_KEY`. The eval workflow reads runs from a DynamoDB Local service container, so the role needs no DynamoDB access beyond the policy above.

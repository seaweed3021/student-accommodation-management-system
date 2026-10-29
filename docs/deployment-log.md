# Deployment 1 Log – Front End

| Item | Detail |
|---|---|
| Date | 22 Oct 2026, 3:40 PM EDT |
| What was deployed | Front-end homepage (frontend/index.html, styles.css) |
| Hosting | GitHub Pages (CloudFront is blocked in the Learner Lab) |
| Method | GitHub Actions workflow "Deploy front end to GitHub Pages" |
| Trigger | Merge of PR #6 into main (commit d155ffb) |
| Steps | checkout, configure-pages, upload-pages-artifact, deploy-pages |
| Duration | 22 seconds (run), 15 seconds (deploy job) |
| Result | Success |
| Live URL | https://seaweed3021.github.io/student-accommodation-management-system/ |
| Errors and fixes | None |
| Verification | Live URL loads and the Actions run shows a green tick |

Note: No AWS keys are used for this deployment.

## Deployment 2 – Cognito login pages

| Item | Detail |
|---|---|
| Date | 29 Oct 2026 |
| What was deployed | login.html, customer.html, owner.html, auth.js, config.js |
| Method | GitHub Actions "Deploy front end to GitHub Pages" (run #2) |
| Trigger | Merge of PR #8 (muskan/cognito-login) into main, commit 99736f6 |
| Duration | 33 seconds |
| Result | Success |
| Errors and fixes | None |

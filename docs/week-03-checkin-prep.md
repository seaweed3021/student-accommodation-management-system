# Week 3 check-in prep – Team RoomSphere

Learning and Progress Update 1.

| Question | Answer |
|---|---|
| 1. Pain point in one sentence | The landlord needs one place to manage rooms, applications and maintenance instead of chasing phone calls, texts, emails and spreadsheets. |
| 2. What did we learn that changed how we build? | Pattern B: private database, managed containers. We dropped EC2 hosting and a public database, and avoided a NAT gateway (about 33 USD a month). When Aneeta checked the Learner Lab, CloudFront distributions were blocked, so the front end moves to S3 static website hosting. |
| 3. What works now? | Learner Lab running with $0 of $50 used; repository with the data model and SQL schema (tested in Docker, merged by pull request #1); Architecture v0. |
| 4. Biggest unknown / blocker, and what we tried | CloudFront is blocked in Learner Lab, which removed the Pattern B front-end design. Aneeta checked service access; we switched to S3 static website hosting. |
| 5. What will be true by Progress Submission 2, and owners | Front end live (Muskan); VPC and private RDS (Aneeta); Cognito groups (Mitesh); one API call end to end (Mitesh and Aneeta). |
| 6. What each member did in Progress Submission 1 | Aneeta: repository and README, Learner Lab, AWS evidence. Mitesh: data model, SQL schema and its test, architecture diagram, pull requests. Muskan: front-end homepage assigned; no commits yet. |

Architecture v0 and the change from Pattern B are in `docs/architecture-v0.png` and Progress Submission 1.

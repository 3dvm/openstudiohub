# Technical Director & Admin Guide

Welcome to the infrastructure core of OpenStudio Hub. This section is dedicated to Technical Directors (TDs), IT administrators, and Production Managers who need to deploy, maintain, and oversee the studio's technical pipeline.

While artists enjoy a seamless, one-click interface, the backend relies on robust networking and version control orchestration.

Navigate through the administrative documentation:

* **[B2B Studio Deployment & Provisioning](admin-guide/deployment.md):** A comprehensive guide to packaging the global configuration into `.seed` files for zero-friction Day 0 deployments.
* **[VCS Abstraction (SVN / Git LFS)](admin-guide/vcs-abstraction.md):** Technical details on how the Hub abstractly supports both SVN and Git LFS under the hood.
* **[Process Guardian & Corruption Prevention](admin-guide/process-guardian.md):** Understand how the Hub protects your repository by preventing orphan server locks and safely handling crash recoveries.

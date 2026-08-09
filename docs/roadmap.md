---
title: Roadmap to v1.0.0
description: Discover the future of OpenStudioHub. A look at our upcoming milestones, from core stabilization to AI-driven telemetry.
icon: material/map
---

# OpenStudioHub: The Road to v1.0.0

Welcome to the **OpenStudioHub** official roadmap. Our goal is to build the most robust, transparent, and seamless open-source pipeline for Blender centric animation studios.

To maintain complete transparency with our community and partners, we have mapped out our exact journey to our first major release (**v1.0.0**). We are committed to a "Zero-Trust" architecture, artist-first tooling, and studio-grade reliability.

---

## Current Status: v0.6.5 - Production Visualization
We have successfully established the foundational sandboxing, dynamic context injection, and strict version control integration (SVN). With v0.6.5, we introduced **Watchtower integration**, allowing production managers to seamlessly review artist playblasts in an ephemeral server.

---

## v0.7.0 - Core Architecture Refactor & Stability (Feature Freeze)
*Taking a step back to leap forward.* Before we introduce advanced AI features and render farm orchestration, we are dedicating an entire milestone to technical excellence.
- **MVC Decoupling:** Completely separating our UI layers (PySide6) from backend operations for a faster, glitch-free experience.
- **Test Coverage:** Introducing comprehensive unit testing and functional testing across all modules to guarantee refactoring ease.
- **Type Hinting & Tech Debt:** Enforcing strict Python typing and purging prototype code to guarantee long-term maintainability.

## v0.8.0 - Core Telemetry & Artist QoL
*Empowering studios with passive data.* No more manual timesheets or lost work.
- **Heartbeat & Idle Tracker:** Automatically detects when an artist steps away, ensuring production timesheets are 100% accurate without intrusive monitoring.
- **Passive Auto-Saves:** Background synchronization with the VCS every 30 minutes to prevent catastrophic data loss.
- **Undo Harvester:** A lightweight data collector that reads Blender's undo stack to understand artist workflows without interrupting them. This will allow easy comments to update the work done on an artist session.

## v0.8.5 - Render Farm & Job Orchestration
*Simplifying deployment.* 
- **Flamenco Integration:** Automated, silent deployment of the Flamenco render farm add-on directly into the artist's sandbox.
- **VFS Orchestration:** Smart routing of heavy render outputs directly to the NAS, bypassing SVN to keep repositories lightning-fast.
- **RBAC Guardrails:** Conditional UI locks to prevent junior artists from accidentally saturating the render farm without lead approval.

## v0.9.0 - The AI Scribe & Daily Digest
*AI assintance designed for production, securely.* 
- **DAURANI Proxy Client:** An internal bridge to our LLM proxy that guarantees zero data leaks. OpenStudioHub will *never* send your proprietary data directly to public AI providers.
- **AI-Enriched Commits:** Translating the raw data from the *Undo Harvester* into perfectly formatted, human-readable commit messages.
- **Daily Stand-up Digest:** A UI dashboard for Production Managers that summarizes the entire studio's progress from the last 24 hours.

## v0.9.5 - Cloud Gateway & Disaster Recovery
*Infrastructure as Code (IaC) for hybrid studios.*
- **DevOps Command Center:** Embedded SSH terminals and Docker node provisioning directly from the TD dashboard.
- **Tailscale Mesh:** Seamlessly connect remote freelancers to your local office NAS.
- **Multi-Tier Backups:** Automated database and SVN backups synced to local HDDs and cold cloud storage (AWS/Backblaze).

## v0.9.9 - Beta Testing & Hardening
*The final crucible.* 
- Full feature freeze and rollout to our pilot B2B clients.
- Implementation of global error logging and crash reporting.
- Intense UI/UX polish, for a AAA software look and feel across 4K displays.

## v1.0.0 - Official Release
*Production Ready.*
- **Multi-OS Support:** Fully agnostic execution across Windows, Linux, and macOS.
- **Standalone Binaries:** Effortless installation via PyInstaller—no Python environments required for the end-user.
- **Comprehensive Studio Documentation:** Detailed guides for TDs to integrate OpenStudioHub into any existing pipeline.

---

## Support & Enterprise Integration

OpenStudioHub is proudly open-source (GPL v3.0) and built for the community. We believe in accessible tools for studios of all sizes, but we also know that production environments require dedicated attention. 

Here is how you can get involved or get help:

### Support the Open-Source Development
If OpenStudioHub is helping your indie team save time and organize your pipeline, consider supporting our late-night coding sessions! Your contributions keep the core project free and actively maintained.
* **Support us on Ko-fi:** [ko-fi.com/3dvm_dev](https://ko-fi.com/3dvm_dev)

### B2B Integration & Support
Implementing a new pipeline in an active studio can be daunting. We offer professional, hands-on integration services to tailor OpenStudioHub to your specific infrastructure.
* **Custom Onboarding:** Let our Production Management and Tech team set up your NAS, VPS, and artist sandboxes.
* **Priority Support:** Get direct technical assistance to ensure your studio's downtime is minimum.

**Ready to upgrade your studio?** 
Reach out to us at **[contact@estudiomacuare.com](mailto:contact@estudiomacuare.com)** to schedule a pipeline consultation.

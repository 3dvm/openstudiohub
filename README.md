# OpenStudio Hub: Pipeline Management System

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)
![Blender](https://img.shields.io/badge/Blender-3.6_|_4.2_|_5.1-orange?logo=blender&logoColor=white)
![Kitsu](https://img.shields.io/badge/Kitsu_SSO-Gazu-success?logo=cgwire&logoColor=white)
![Architecture](https://img.shields.io/badge/Architecture-MVC-purple)

**OpenStudio Hub** is a standalone desktop application designed to orchestrate the production pipeline for a 3D animation studio. It acts as a seamless, deterministic bridge between artists, the version control system (SVN/NAS), and the production tracker (Kitsu).

> 🎬 **[Watch the Demo Video Showcase Here](https://estudiomacuare.com/wp-content/uploads/openstudio-hub-demo.mp4)**

---

## 🐘 The Elephant in the Room: Blender Studio Tools

Any studio working with Blender has looked with envy at the Blender Foundation's official pipeline. Tools like the `asset_pipeline` (designed to enable simultaneous work on the same asset) and `blender_kitsu` (which connects the 3D interface directly with the production manager) are, on paper, a Technical Director's dream come true.

However, there is an "elephant in the room" that few talk about: **these tools are not *plug-and-play*.**

Implementing the Blender Studio Tools ecosystem outside the Foundation's walls requires overcoming a brutal technical learning curve. If your studio doesn't replicate their exact network infrastructure, use their strict SVN configuration, or if you have artists working remotely on Windows instead of Linux, integration usually ends in broken scripts, lost paths, and hours of frustration for the IT team.

Here is where **OpenStudio Hub** comes in. Designed under a "zero friction" philosophy, it doesn't seek to reinvent the wheel, but to tame it. It works as a smart Sandbox environment that packages, pre-configures, and standardizes these powerful core tools, making them accessible to any studio—from an indie team to a mid-sized production company—with just a couple of clicks.

---

## ⚠️ The Problem: Changing Blender versions.
In large-scale productions, updating software versions or add-ons mid-show often breaks backward compatibility. Artists waste hours dealing with Python tracebacks, missing add-ons, and manual path configurations just to open a legacy file without corrupting modern production data.

## 💡 The Solution: A "rez-like" Ephemeral Sandbox
OpenStudio Hub solves this by reading the "DNA" (`project_config.json`) of each project and **building dynamic software containers at runtime**. It bypasses global OS installations completely by injecting environment variables (`BLENDER_USER_RESOURCES`, `BLENDER_USER_SCRIPTS`) to isolate extensions, wheels, and preferences per project. 

This guarantees **100% backward compatibility** and allows artists to run conflicting legacy tools (e.g., Blender 3.6) and modern pipelines (e.g., Blender 5.1) simultaneously with zero cross-contamination.

---

## 🏗️ High-Level Studio Architecture

```mermaid
flowchart TD
    subgraph Cloud [Studio Cloud Infrastructure]
        K[🦊 Kitsu API<br>SSO & Assignments]
        N[☁️ NAS<br>Software Vault & Manifests]
        S[🐘 SVN Server<br>Production Assets & Shots]
    end

    subgraph Workstation [Artist Local Machine]
        direction TB
        MH{⚙️ OpenStudio Hub<br>Standalone Executable}
        RAM[(🧠 In-Memory Vault<br>Volatile Credentials)]
        SB[📦 Ephemeral Sandbox<br>./06_conf_LOCAL/]
        DCC[🎨 Blender Subprocess]
    end

    K <-->|Role Auth / JSON| MH
    N -->|Downloads Add-ons .zip| MH
    MH -->|Writes Extensions & Configs| SB
    MH -->|Stores Passwords temporarily| RAM
    
    RAM -.->|Injects ENV variables| DCC
    SB -.->|BLENDER_USER_RESOURCES override| DCC
    DCC <-->|Commits/Updates Data| S

    classDef cloud fill:#2c3e50,stroke:#fff,stroke-width:2px,color:#fff;
    classDef local fill:#34495e,stroke:#fff,stroke-width:2px,color:#fff;
    classDef hub fill:#e67e22,stroke:#fff,stroke-width:3px,color:#fff;
    classDef security fill:#e74c3c,stroke:#fff,stroke-width:2px,color:#fff;

    class K,N,S cloud;
    class SB,DCC local;
    class MH hub;
    class RAM security;

```

---

## 🔒 Security: Just-In-Time (JIT) Credential Interception

Traditional pipelines often rely on saving plain-text network credentials on local disks, creating significant security vulnerabilities. OpenStudio Hub utilizes an **In-Memory Vault**. SVN and Kitsu passwords are asked once via a CustomTkinter modal, kept strictly in volatile RAM, injected into the DCC as OS environment variables during the subprocess launch, and wiped entirely upon logout.

```mermaid
sequenceDiagram
    autonumber
    actor Artist
    participant UI as OpenStudio Hub GUI
    participant Vault as RAM Vault (Volatile)
    participant Core as Env Launcher
    participant DCC as Blender Subprocess

    Artist->>UI: Clicks "Launch Project"
    UI->>Vault: Check SVN/Kitsu Credentials
    
    alt Vault is Empty
        Vault-->>UI: Missing Credentials
        UI->>Artist: Prompt JIT Login Modal
        Artist->>UI: Enters Passwords
        UI->>Vault: Store in RAM (No Disk IO)
    end
    
    UI->>Core: Trigger Thread (project_config.json)
    Core->>Vault: Retrieve Credentials
    Core->>Core: Inject Kitsu/SVN ENV variables
    Core->>Core: Override DCC User Paths
    Core->>DCC: subprocess.Popen()
    
    Note over DCC: DCC boots 100% isolated.<br/>Init scripts read ENVs<br/>and auto-authenticate.

```

---

## 💻 Development & Installation

The codebase is designed following the **Separation of Concerns (MVC)** principle, making it highly maintainable for Enterprise scaling.

1. Clone the repository:

```bash
git clone [https://github.com/tu-usuario/openstudio-hub.git](https://github.com/tu-usuario/openstudio-hub.git)
cd openstudio-hub

```

2. Create and activate the virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows

```

3. Install dependencies:

```bash
pip install -r requirements.txt

```

4. Run the Hub:

```bash
python openstudio_hub.py

```

## 📦 Packaging for Production

To distribute the tool to studio artists without requiring them to install Python, the application is "frozen" into a standalone executable using PyInstaller.

```bash
pyinstaller --noconsole --onefile --name "OpenStudio Hub" openstudio_hub.py

```

*(Note: The compiled executable is not tracked in this repository. Please visit the **Releases** tab to download the latest production build).*

---

*Developed by Ernesto Del Valle M. - Pipeline TD & Technical Artist.*

# The Daily Workflow: Work & Publish

OpenStudio Hub simplifies your daily routine into two main actions: clicking **Work** to start, and clicking **Publish** when you are ready for review. 

## 1. Starting your Task (The "Work" Button)
When you find your assigned task on the dashboard, simply click the **Work** button. 
* **What happens?** The Hub automatically launches your isolated Blender environment and opens your `.blend` file. 
* **Dynamic Creation:** If the file doesn't exist yet, the Hub's Shot Builder dynamically generates it from the studio template so you don't start with an empty canvas.
* **Context Injection:** The interface is pre-navigated to your specific task context, and only the tools you need (like the Flamenco Render Farm for lighting artists) are enabled.

## 2. Working & Telemetry
While you work, the Hub operates silently in the background:
* **Auto-Save:** The system enforces an automatic save of your `.blend` file every 30 minutes.
* **Idle Tracking:** An idle tracker pauses your time logging if you step away from your workstation for more than 5 minutes, ensuring your timesheets are perfectly accurate.

## 3. Submitting your Work (The "Push / Publish" Button)
When your task is ready for review, hit **Publish**. Before the file is uploaded, the **Gatekeeper** audits your scene.
* **Silent Cleanup:** It automatically purges orphan data and ignores temporary collections (like `__TEMP__`).
* **The Concierge Pop-up:** If you accidentally linked a texture or HDRI from your personal `Downloads` folder, the Hub will intercept the publish and show a pop-up. It will ask you to classify the file, and then it will automatically copy it to the correct server folder and fix the paths for you.
* **Scale Auto-Fix:** If any of your meshes have unapplied rotations or scales, the Gatekeeper will apply them automatically to prevent broken rigs down the line.

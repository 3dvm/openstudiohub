# Process Guardian & Corruption Prevention

Data corruption and stuck server locks are among the most frustrating issues for Technical Directors to resolve. OpenStudio Hub acts as a strict **Process Guardian** to ensure the repository remains healthy, even during abrupt system failures.

## Lock Prevention & Application Sandboxing
When an artist opens a file, the Hub claims a lock on the Version Control Server to prevent other artists from overwriting the work. 
* If the artist attempts to close the OpenStudio Hub while their 3D application is still running, the Hub blocks its own closure. 
* This strict behavior prevents version control locks from remaining stuck on the server, which would otherwise freeze production for that specific asset.

## Crash Recovery Policy
Power outages and forced shutdowns happen. To handle these scenarios, the Hub features an automated recovery policy:
* **Pre-Flight Cleanup:** Before launching a new session, the Hub's thread executes a `cleanup()` method to sanitize the local workspace.
* **Local Lock Resolution:** If the system detects that a file is locked, but the lock belongs to the current active user from a previously crashed session, the Hub ignores the error, declares a "Recovered Session," and safely launches the software.

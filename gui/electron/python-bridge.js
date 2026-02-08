const { spawn } = require("child_process");
const path = require("path");

/**
 * Manages spawning and communicating with cli.py as a subprocess.
 */
class PythonBridge {
  constructor() {
    this.process = null;
    /** Path to cli.py (one level up from gui/) */
    this.cliPath = path.join(__dirname, "..", "..", "cli.py");
  }

  /**
   * Build the CLI arguments array from a config object.
   */
  _buildArgs(config) {
    const args = [this.cliPath];

    if (config.inputDir) args.push("--input", config.inputDir);
    if (config.outputDir) args.push("--output", config.outputDir);
    if (config.baseGameDir) args.push("--base-game", config.baseGameDir);
    if (config.overlaysDir) args.push("--overlays", config.overlaysDir);
    if (config.blenderPath) args.push("--blender-path", config.blenderPath);
    if (config.workers) args.push("--workers", String(config.workers));
    if (config.dlcs && config.dlcs.length > 0)
      args.push("--dlcs", config.dlcs.join(","));
    if (config.categories && config.categories.length > 0)
      args.push("--categories", config.categories.join(","));

    // Render settings
    if (config.taaSamples) args.push("--taa-samples", String(config.taaSamples));
    if (config.renderSize) args.push("--render-size", String(config.renderSize));
    if (config.supersampling)
      args.push("--supersampling", String(config.supersampling));
    if (config.outputSize) args.push("--output-size", String(config.outputSize));
    if (config.webpQuality)
      args.push("--webp-quality", String(config.webpQuality));
    if (config.noGreenFix) args.push("--no-green-fix");
    if (config.force) args.push("--force");

    // Mode
    if (!config.render3d) args.push("--no-render-3d");

    return args;
  }

  /**
   * Run --scan-only and return the parsed JSON result.
   */
  async runScanOnly(config) {
    return new Promise((resolve, reject) => {
      const args = this._buildArgs(config);
      args.push("--scan-only");

      let stdout = "";
      let stderr = "";

      const proc = spawn("python", args, {
        windowsHide: true,
      });

      proc.stdout.on("data", (data) => {
        stdout += data.toString();
      });
      proc.stderr.on("data", (data) => {
        stderr += data.toString();
      });

      proc.on("close", (code) => {
        if (code !== 0) {
          reject(new Error(`scan-only exited with code ${code}: ${stderr}`));
          return;
        }
        // The JSON output is the last chunk — find the JSON object
        try {
          const jsonMatch = stdout.match(/\{[\s\S]*\}$/m);
          if (jsonMatch) {
            resolve(JSON.parse(jsonMatch[0]));
          } else {
            reject(new Error("No JSON output from scan-only"));
          }
        } catch (e) {
          reject(new Error(`Failed to parse scan-only output: ${e.message}`));
        }
      });

      proc.on("error", (err) => {
        reject(new Error(`Failed to start Python: ${err.message}`));
      });
    });
  }

  /**
   * Start processing with --json-progress, streaming lines to callback.
   */
  startProcess(config, onLine) {
    this.kill(); // Kill any existing process

    const args = this._buildArgs(config);
    args.push("--json-progress");
    if (config.dryRun) args.push("--dry-run");

    this.process = spawn("python", args, {
      windowsHide: true,
    });

    let buffer = "";

    this.process.stdout.on("data", (data) => {
      buffer += data.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop(); // Keep incomplete line in buffer

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const parsed = JSON.parse(trimmed);
          onLine(parsed);
        } catch {
          // Non-JSON output (text logs) — send as log line
          onLine({ type: "log", message: trimmed });
        }
      }
    });

    this.process.stderr.on("data", (data) => {
      const msg = data.toString().trim();
      if (msg) onLine({ type: "log", message: msg });
    });

    this.process.on("close", (code) => {
      if (code !== 0 && code !== null) {
        onLine({
          type: "error",
          message: `Process exited with code ${code}`,
        });
      }
      this.process = null;
    });

    this.process.on("error", (err) => {
      onLine({
        type: "error",
        message: `Failed to start: ${err.message}`,
      });
      this.process = null;
    });
  }

  /**
   * Kill the running Python process.
   */
  kill() {
    if (this.process) {
      this.process.kill();
      this.process = null;
    }
  }
}

module.exports = { PythonBridge };

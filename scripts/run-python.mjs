import { spawnSync } from "node:child_process";

const candidates = [
  ["python"],
  ["py", "-3"],
  ["python3"],
];

function findPythonCommand() {
  for (const command of candidates) {
    const probe = spawnSync(command[0], [...command.slice(1), "--version"], {
      stdio: "ignore",
      shell: false,
    });
    if (probe.status === 0) {
      return command;
    }
  }
  return null;
}

const pythonCommand = findPythonCommand();
if (!pythonCommand) {
  console.error(
    "No Python interpreter found. Install Python and ensure one of these works: " +
      "`python`, `py -3`, or `python3`.",
  );
  process.exit(1);
}

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error("No Python arguments provided.");
  process.exit(1);
}

const result = spawnSync(pythonCommand[0], [...pythonCommand.slice(1), ...args], {
  stdio: "inherit",
  shell: false,
});

if (typeof result.status === "number") {
  process.exit(result.status);
}

process.exit(1);

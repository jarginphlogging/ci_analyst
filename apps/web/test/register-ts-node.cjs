const path = require("node:path");

process.env.TS_NODE_PROJECT = path.join(__dirname, "..", "tsconfig.test.json");
process.env.TS_NODE_TRANSPILE_ONLY = "true";

require("ts-node/register");

import { AgentWorkspace } from "@/components/agent-workspace";
import { serverEnv } from "@/lib/server-env";

export default function Home() {
  const initialEnvironment = serverEnv.WEB_BACKEND_MODE === "web_mock" ? "Mock" : "Sandbox";
  return <AgentWorkspace initialEnvironment={initialEnvironment} />;
}

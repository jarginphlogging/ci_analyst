import { AgentWorkspace } from "@/components/agent-workspace";

export default function Home() {
  const initialEnvironment = "Sandbox";
  return <AgentWorkspace initialEnvironment={initialEnvironment} />;
}

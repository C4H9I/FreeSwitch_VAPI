from signalwire_agents import AgentBase


class HelloAgent(AgentBase):
    def __init__(self):
        super().__init__(name="hello")
        self.prompt_add_section("Role", "You are a friendly assistant.")


if __name__ == "__main__":
    agent = HelloAgent()
    agent.run()

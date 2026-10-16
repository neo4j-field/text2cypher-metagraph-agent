"""
Text2Cypher ReAct Agent
Translates natural language into Cypher queries against Neo4j using native tools.
Architecture: ReAct agent (prompt-driven flow) + native Neo4j Python driver tools.
"""

import asyncio
import json
import os

from dotenv import load_dotenv
from langchain_core.messages import AnyMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langchain_core.tools import tool
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.chat_agent_executor import AgentState
from neo4j import GraphDatabase

if load_dotenv():
    print("Loaded .env file")
else:
    print("No .env file found")


# --- Neo4j driver (shared) ---
_driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    auth=(os.getenv("NEO4J_USERNAME", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
    max_connection_lifetime=200,   # recycle connections before the server closes them
    keep_alive=True,
)


# --- Tools ---
# @tool
# def get_neo4j_full_schema() -> str:
#     """Get the schema of the Neo4j database: all node labels, their properties,
#     and their relationships to other node labels. Always call this before writing
#     any Cypher query."""
#     query = "CALL apoc.meta.schema() YIELD value RETURN value"
#     def _run(tx):
#         result = tx.run(query)
#         return [record.data() for record in result]
#     with _driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
#         schema = session.execute_read(_run)
#     return json.dumps(schema, default=str)

@tool
def term_lookup(terms: list[str]) -> str:
    """
    Used to lookup node labels by term. For each term a full text-index search will be executed.
    The results for each term are a collection of label, nodeElementId, nodeProperties, and score.
    Use this tool to look up candidate node labels to use in other tools.
    """
    print(f"Terms: {terms}")
    query = """
    UNWIND $terms as term
    WITH term
    CALL (term) {
    CALL db.index.fulltext.queryNodes("full_text_idx", term) YIELD node, score
    WITH 
        CASE WHEN node:__NodeLabel__
            THEN node.label
            ELSE apoc.text.join([x IN labels(node) WHERE NOT x IN ['Resource','CustomerData']],':')
        END as label,
        node,
        score  
    ORDER BY score DESC LIMIT 10
    
    RETURN collect({label:label,
        nodeElementId:elementId(node),
        nodeProperties:apoc.map.fromPairs([k in keys(node) WHERE NOT k CONTAINS 'embedding' | [k,node[k]]]),
        score:score}) AS results
    }
    RETURN term, results
    """
    def _run(tx):
        result = tx.run(query, {"terms": terms})
        return [record.data() for record in result]
    with _driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
        results = session.execute_read(_run)
    return json.dumps(results, default=str)

@tool
def get_node_properties(node_labels: list[str]) -> str:
    """Get the relevant properties for the given node labels, 
    including properties on neighboring nodes and relationships: 
    Always call this before writing any Cypher query."""
    query = """
    WITH $node_labels as node_labels
    UNWIND node_labels as nodeLabel
    MATCH p=(node:__NodeLabel__ {label:nodeLabel})--(rt:__RelationshipType__)--(other:__NodeLabel__)
    WHERE rt.type = 'hasAttribute'
            AND other.label <> 'Resource'
    WITH nodeLabel, node_labels, apoc.coll.toSet(apoc.coll.flatten(
            collect([otherNode IN nodes(p) WHERE otherNode:__NodeLabel__ AND NOT otherNode = node | otherNode]))) AS neighborhoodNodeList
    
    RETURN
        'Node properties:\n' +
        'These are all accessible via including a :hasAttribute path from the node, e.g\n' +
        '(:' + nodeLabel + ')-[:hasAttribute]-(:' + neighborhoodNodeList[0].label + ')\n\n' + 
        apoc.text.join([
            node IN neighborhoodNodeList |
            node.label + ' {' +
            apoc.text.join([(node)-[:HAS_PROPERTY]-(pd) | pd.key + ': ' + pd.type], ', ')
            + '}'
        ], '\n') as llmSchemaText
"""
    def _run(tx):
        result = tx.run(query, {"node_labels": node_labels})
        return [record.data() for record in result]
    with _driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
        schema = session.execute_read(_run)
    return json.dumps(schema, default=str)

@tool
def get_neo4j_sub_schema(labels: list[str]) -> str:
    """Get the relevant sub-schema of the Neo4j database for the given labels: 
    Always call this before writing any Cypher query.
    Do not use if input labels is empty or only contains 1 label, as the query is designed to find paths between multiple labels."""
    query = """
WITH $labels as labels
UNWIND range(0,size(labels)-1) as index1
UNWIND range(index1+1,size(labels)-1) as index2
WITH labels[index1] as label1, labels[index2] as label2
MATCH p=ALL SHORTEST (n:__NodeLabel__ {label:label1})
                ((l1:__NodeLabel__ WHERE l1.label <> 'Resource')--(:__RelationshipType__)--(l2:__NodeLabel__ WHERE l2.label <> 'Resource')){0,3}
                (end:__NodeLabel__ {label:label2})
WITH p, nodes(p) as pathNodes, size(nodes(p)) as numNodes
UNWIND range(0,numNodes-1) as index
WITH p, pathNodes[index] as currentNode, pathNodes[index-1] as prevNode
WITH p, currentNode, prevNode, CASE 
  WHEN currentNode:__RelationshipType__
   AND head([(x)<-[:START_NODE_LABEL]-(currentNode) | x]) = prevNode 
  THEN 'forward' ELSE 'reverse' END as direction
WITH p, CASE 
     WHEN currentNode:__NodeLabel__ THEN '(:' + currentNode.label + ')'
     WHEN currentNode:__RelationshipType__ AND direction = 'forward' THEN '-[:' + currentNode.type + ']-'
     WHEN currentNode:__RelationshipType__ AND direction = 'reverse' THEN '-[:' + currentNode.type + ']-'
     ELSE ''
     END as pathToken
WITH p, collect(pathToken) as pathTokens
RETURN apoc.text.join(pathTokens, '') as pathStr
"""
    def _run(tx):
        result = tx.run(query, {"labels": labels})
        return [record.data() for record in result]
    with _driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
        schema = session.execute_read(_run)
    return json.dumps(schema, default=str)

@tool
def read_neo4j_cypher(query: str, params: dict = {}) -> str:
    """Execute a READ-ONLY Cypher query against the Neo4j database and return
    the results as JSON. Never use this for write operations.

    Args:
        query: The Cypher query to execute.
        params: Optional parameters to pass to the query.
    """
    def _run(tx):
        result = tx.run(query, params)
        return [record.data() for record in result]
    with _driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
        records = session.execute_read(_run)
    return json.dumps(records, default=str)


tools = [term_lookup, get_neo4j_sub_schema, read_neo4j_cypher, get_node_properties]


# --- System Prompt ---
SYSTEM_PROMPT = """You are a Neo4j Cypher expert and data analyst.
Your job is to translate natural language questions into Cypher queries, execute them
against the Neo4j database, and return clear answers.

The database uses an RDF-style data model. Some properties are stored directly on nodes, 
while others are represented as separate "Resource" nodes connected by :hasAttribute relationships. 
The schema is complex and may have multiple paths to connect concepts.

As a Cypher expert, when writing queries:
* You MUST pick out key concepts from user queries and use the term_lookup tool
   * Usage: pick out key words from questions and stem them if needed
     * Example: What samples have temperature data?
     * Key concepts (i.e. terms) to use: ['samples','sample','temperature']
     * Note that sample was added by dropping the '-s'. Reason: lucene full-text index does not do stemming
   * Exceptions: user data analysis questions returned from previous queries
* You MUST always retrieve the database schema first using `get_neo4j_sub_schema` before
  writing any Cypher query. Use the term_lookup tool to get a reduced set of node labels.
  Do not guess node labels, relationship types, or property names.
* Use the schema to determine correct node labels, relationship types, property names
* If a query returns an error from the database, analyze the error, refactor your query,
  and try again. You may retry up to 3 times before asking the user for clarification.
* If an empty result is returned, consider whether the query is correct or whether the
  data simply does not exist. Inform the user accordingly.
* Use `variable.property IS NOT NULL` to check property existence.
* Always use parameterized queries when possible.
* Write READ-ONLY queries. Never modify data.
* Make all relationship traversals directionless, e.g. `(a)-[:REL]-(b)` instead of `(a)-[:REL]->(b)`
* Do not use any variable length traversals (e.g. `*`, `*1..3`) in your queries, as they can be very expensive on large graphs.
* put a limit on the number of results returned, e.g. `RETURN ... LIMIT 10`, to avoid overwhelming the user with data.
* for general data exploration queries or min/max queries, you will need to put an ORDER BY before the LIMIT to ensure you are returning the most relevant results.

Returning results:
* When returning information, don't return nodes. Look for a suitable node attribute to return 
  instead (e.g., name, value, etc.) and return that with a descriptive key. The attribute may
  be on a neighboring rdf node rather than the main node of interest, so check the schema carefully.
* always call the `get_node_properties` tool for any node labels in your query to find out what properties are available, including on neighboring nodes.

When responding to the user:
* Provide clear, conversational answers grounded in the actual query results.
* Cite the underlying data - include relevant property values in your response.
* If the user question is ambiguous, ask a clarifying question rather than guessing.
* If the user refers to something from a previous turn (e.g., "that drug", "filter those"),
  use conversation context to resolve the reference.

Few-shot examples:
Use these as examples of well-formed questions and Cypher queries, but do not reference them directly in your responses.
* Question: What ingredients have been used in relation to cheese? 
* Cypher:
  match (cheese:Cheese)<-[:hasAttribute]-(sample:Sample) 
  match (sample)-[:hasPart]->(ingredient:Ingredient) 
  where ingredient.value is not null 
  return 
  ingredient.value
  limit 10 
"""


# --- Pre-model hook: trim conversation history to fit context window ---
def pre_model_hook(state: AgentState) -> dict[str, list[AnyMessage]]:
    """Trim messages before each LLM call to stay within token limits."""
    trimmed_messages = trim_messages(
        state["messages"],
        strategy="last",
        token_counter=count_tokens_approximately,
        max_tokens=30_000,
        start_on="human",
        end_on=("human", "tool"),
        include_system=True,
    )
    return {"llm_input_messages": trimmed_messages}


# --- Stream printer ---
async def print_stream(async_stream, output_messages_key="llm_input_messages"):
    """Print agent stream output showing the ReAct thought process."""
    async for chunk in async_stream:
        for node, update in chunk.items():
            messages_key = (
                output_messages_key if node == "pre_model_hook" else "messages"
            )
            for message in update[messages_key]:
                if isinstance(message, tuple):
                    print(message)
                else:
                    message.pretty_print()
        print()


# --- Main ---
async def main():
    llm = ChatAnthropic(
        model="claude-sonnet-4-6",
        temperature=0,
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        base_url=os.getenv("ANTHROPIC_BASE_URL"),
    )

    agent = create_react_agent(
        llm,
        tools,
        pre_model_hook=pre_model_hook,
        checkpointer=InMemorySaver(),
        prompt=SYSTEM_PROMPT,
    )

    config = {"configurable": {"thread_id": "1"}}

    print(f"Tools available: {[t.name for t in tools]}")
    print("\n===== Text2Cypher ReAct Agent =====")
    print("Ask questions about the Neo4j database in natural language.")
    print("Type 'exit', 'quit', or 'q' to stop.\n")

    while True:
        user_input = input("User> ")
        if user_input.strip().lower() in {"exit", "quit", "q"}:
            _driver.close()
            print("Exiting...")
            break

        await print_stream(
            agent.astream(
                {"messages": user_input},
                config=config,
                stream_mode="updates",
            )
        )


if __name__ == "__main__":
    asyncio.run(main())

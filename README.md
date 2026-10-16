# text2cypher-metagraph-agent

## Configuration

Copy `.env.example` to `.env` and fill in your Neo4j and Anthropic credentials. Never commit `.env`.

## New Database Setup Instructions

### Materialize the meta graph

* Run setup/create_metagraph_shared_properties.cypher

### Add semantic_text to \_\_NodeLabel\_\_ nodes

For data model:

1. Run `setup/node_label_input_to_llm_for_semantic_text_generation.cypher`
2. Download the output of the query as a CSV
3. Rename the exported CSV to node_label_example_prop_value.csv
4. Place the renamed file in ./setup
5. Run `python ./anthropic-get-nodelabel-descriptions.py`
6. This will generate `node_label_description.cypher`
7. Run the Cypher statements in `node_label_description.cypher` in the Neo4j browser


### Add CustomerData and CustomerOntology labels

Run these two Cypher statements in the Neo4j Browser

```
:auto
// set CustomerData
MATCH (n:Resource)
WHERE n.uri CONTAINS 'customer.data.com'
WITH n
CALL (n) {
    SET n:CustomerData
} IN TRANSACTIONS OF 5000 ROWS;
```

MATCH (n:__Entity__)
RETURN count(n)

MATCH (n)
WHERE n.value IS NOT NULL
SET n:CustomerData;

MATCH (n:__PropertyDefinition__) REMOVE n:CustomerData


```
:auto
// set CustomerOntology
MATCH (n:Resource)
WHERE NOT n.uri CONTAINS 'customer.data.com'
WITH n
CALL (n) {
    SET n:CustomerOntology
} IN TRANSACTIONS OF 5000 ROWS;
```

### Add the Fulltext index

Run this Cypher statement in the Neo4j Browser

```
CREATE FULLTEXT INDEX full_text_idx IF NOT EXISTS
FOR (n:__NodeLabel__|CustomerData)
ON EACH [n.semantic_text, n.label, n.value];
```
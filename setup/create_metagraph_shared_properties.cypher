// create metagraph (data model+node labels+relationship types+property definitions) based off of apoc.meta.schema
//   change apoc.meta.schema 'sample' value as appropriate - smaller sample values run faster but may miss schema elements

MERGE (dataModel:__DataModel__ {name: 'DataModel'})
WITH dataModel
//CALL apoc.meta.schema() YIELD value
CALL apoc.meta.schema({sample: 1000}) YIELD value   // use sample to control how much graph is walked
UNWIND keys(value) as key
WITH dataModel, key, value[key] as value
WITH dataModel, key, value, value.type as type
CALL (*) {
    WITH *
    WHERE type = 'node' AND NOT (key STARTS WITH '__' and key ENDS WITH '__')

    // add node label
    MERGE (nl:__NodeLabel__ {label:key})
    MERGE (dataModel)-[:HAS_NODE_LABEL]->(nl)

    WITH dataModel, key, value, nl

    // add node properties
    UNWIND keys(value.properties) as propKey
    WITH dataModel, key, value, nl, propKey, value.properties[propKey] as valueMap
    WITH dataModel, key, value, nl, propKey, valueMap, valueMap['type'] as dataType

    // MERGE (pd:__PropertyDefinition__ {container: key, key: propKey})
    MERGE (pd:__PropertyDefinition__ {id: propKey + '_' + dataType})
    // SET pd += value.properties[propKey]
    SET pd.key = propKey, pd.type = dataType
    MERGE (nl)-[:HAS_PROPERTY]->(pd)
    WITH key, value, nl, collect(pd) as _

    UNWIND keys(value.relationships) as relKey
    WITH key, nl, relKey, value.relationships[relKey] as relValue
    WHERE relValue.direction = 'out' AND NOT relKey IN ['HAS_NODE_LABEL','HAS_RELATIONSHIP_TYPE','START_NODE_LABEL','END_NODE_LABEL','HAS_PROPERTY']
    CALL (dataModel, key, nl, relKey, relValue) {
        UNWIND relValue.labels as endLabel

        WITH dataModel, key, nl, relKey, relValue, endLabel
        WHERE NOT (endLabel STARTS WITH '__' and endLabel ENDS WITH '__')

        // add relationship type
        MERGE (rt:__RelationshipType__ {key: key + '_' + relKey + '_' + endLabel})        
        SET rt.type = relKey
        MERGE (dataModel)-[:HAS_RELATIONSHIP_TYPE]->(rt)

        // connect to start node label
        MERGE (startNodeLabel:__NodeLabel__ {label: key})
        MERGE (rt)-[:START_NODE_LABEL]->(startNodeLabel)

        // connect to end node label
        MERGE (endNodeLabel:__NodeLabel__ {label: endLabel})
        MERGE (rt)-[:END_NODE_LABEL]->(endNodeLabel)

        WITH rt, endLabel, relValue, key        

        // add rel properties
        UNWIND keys(relValue.properties) as relPropKey
        WITH rt, endLabel, relValue, key, relPropKey, relValue.properties[relPropKey] as valueMap
        WITH rt, endLabel, relValue, key, relPropKey, valueMap, valueMap['type'] as dataType
        // MERGE (pd:__PropertyDefinition__ {container: key, key: relPropKey})
        MERGE (pd:__PropertyDefinition__ {id: relPropKey + '_' + dataType})
        // SET pd += relValue.properties[relPropKey]
        SET pd.key = relPropKey, pd.type = dataType

        MERGE (rt)-[:HAS_PROPERTY]->(pd)

        WITH rt, collect(endLabel) as _
        RETURN true as returnValue
    }
    RETURN returnValue
}
RETURN returnValue

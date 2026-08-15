from typing import Annotated, cast

from fastapi import Depends, Request

from darkpulse.config import Settings
from darkpulse.storage.mongodb import MongoManager
from darkpulse.storage.neo4j import Neo4jManager


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_mongo(request: Request) -> MongoManager:
    return cast(MongoManager, request.app.state.mongo)


def get_neo4j(request: Request) -> Neo4jManager:
    return cast(Neo4jManager, request.app.state.neo4j)


SettingsDep = Annotated[Settings, Depends(get_settings)]
MongoDep = Annotated[MongoManager, Depends(get_mongo)]
Neo4jDep = Annotated[Neo4jManager, Depends(get_neo4j)]

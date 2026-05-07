import os
import time
import logging
from typing import Dict, List
from pymongo import MongoClient
import traci

from .sumo_road_map import SUMO_ROADS

logger = logging.getLogger(__name__)

class MongoSumoInjector:
    def __init__(self, mongo_uri: str, db_name: str, collection_name: str):
        self.client = None
        self.collection = None
        self.connected = False
        
        # Don't fail the backend if Mongo isn't running, just gracefully skip injection
        try:
            self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            self.collection = self.client[db_name][collection_name]
            self.client.admin.command('ping')
            self.connected = True
            logger.info(f"[INJECTOR] Connected to MongoDB: {db_name}.{collection_name}")
        except Exception as e:
            logger.error(f"[INJECTOR] Failed to connect to MongoDB: {e}")

    def inject_pending_vehicles(self):
        """
        Query MongoDB for unprocessed records, inject them via TraCI,
        and mark them as processed.
        """
        if not self.connected or self.collection is None:
            return

        try:
            # Find documents that have not been processed
            docs = list(self.collection.find({"processed": {"$ne": True}}).limit(100))
            if not docs:
                return

            injected_count = 0
            
            for doc in docs:
                road_id = doc.get("roadId")
                entry_edge = doc.get("entryEdge")
                vehicles = doc.get("vehicles", [])
                
                # Verify edge is known in the map
                is_valid_road = False
                if road_id and road_id in SUMO_ROADS:
                    entry_edge = SUMO_ROADS[road_id]["entryEdge"]
                    is_valid_road = True
                elif entry_edge:
                    # check if the entry edge is in values
                    if any(v["entryEdge"] == entry_edge for v in SUMO_ROADS.values()):
                        is_valid_road = True
                
                if not is_valid_road or not entry_edge:
                    logger.warning(f"[INJECTOR] Skipping doc {doc.get('_id')} - Invalid road/edge")
                    self._mark_processed(doc["_id"])
                    continue
                
                # Check if route exists, if not, create a dummy one just for the edge
                # In SUMO, vehicles need a route. If the route file provides one we can use it,
                # else we create an ad-hoc route.
                route_id = f"route_{entry_edge}"
                try:
                    if route_id not in traci.route.getIDList():
                        # Just add a route that starts at the entry edge
                        traci.route.add(route_id, [entry_edge])
                except Exception as e:
                    logger.error(f"[INJECTOR] Error checking/adding route {route_id}: {e}")
                    self._mark_processed(doc["_id"])
                    continue
                
                # Inject vehicles
                for veh_data in vehicles:
                    v_type = veh_data.get("type", "car")
                    count = veh_data.get("count", 0)
                    
                    for i in range(count):
                        # Generate unique ID
                        v_id = f"inj_{entry_edge}_{v_type}_{int(time.time() * 1000)}_{injected_count}_{i}"
                        
                        try:
                            # Verify vehicle type exists in SUMO, else fallback
                            # Sometimes custom vehicle types are not loaded.
                            # Just use 'car' if 'type' is not strictly loaded.
                            try:
                                traci.vehicle.add(v_id, route_id, typeID=v_type)
                            except traci.TraCIException:
                                # Type might not exist in the SUMO config, fallback to default 'car' or whatever is available
                                traci.vehicle.add(v_id, route_id)
                                
                            injected_count += 1
                        except Exception as e:
                            logger.error(f"[INJECTOR] Failed to add vehicle {v_id}: {e}")
                
                self._mark_processed(doc["_id"])
                
            if injected_count > 0:
                logger.info(f"[INJECTOR] Injected {injected_count} vehicles from {len(docs)} documents.")

        except Exception as e:
            logger.error(f"[INJECTOR] Error during injection cycle: {e}")

    def _mark_processed(self, doc_id):
        try:
            self.collection.update_one(
                {"_id": doc_id},
                {"$set": {"processed": True, "processedAt": time.time()}}
            )
        except Exception as e:
            logger.error(f"[INJECTOR] Error marking doc {doc_id} as processed: {e}")

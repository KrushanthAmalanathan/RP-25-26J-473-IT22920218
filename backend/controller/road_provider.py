# backend/controller/road_provider.py
"""
Road count providers: unified interface for getting traffic counts from various sources.

Supports:
- FakeProvider: generates synthetic traffic (for N/E/S)
- HybridProvider: combines fake (N/E/S) + YOLO camera (WEST)
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class RoadProviderBase(ABC):
    """Abstract base for road count providers."""
    
    @abstractmethod
    def get_counts(self) -> Dict[str, Dict[str, int]]:
        """
        Get vehicle counts for all roads.
        
        Returns:
            {
                "west_entry": {"car": N, "bike": N, ...},
                "j1_north_entry": {...},
                "j8_north_entry": {...},
                "j8_east_entry": {...},
                "j8_south_entry": {...}
            }
        """
        pass
    
    @abstractmethod
    def get_metadata(self) -> Dict:
        """
        Get metadata about data sources.
        
        Returns:
            {
                "west_source": "camera|fake",
                "camera_ok": bool,
                "last_frame_ts": float,
                ...
            }
        """
        pass


class FakeProvider(RoadProviderBase):
    """
    Generates synthetic traffic for all roads.
    Wraps yolo_fake_generator without changes.
    """
    
    def __init__(self, fake_generator):
        """
        Args:
            fake_generator: YoloFakeGenerator instance
        """
        self.fake_gen = fake_generator
        logger.info("FakeProvider initialized (all roads use synthetic data)")
    
    def get_counts(self) -> Dict[str, Dict[str, int]]:
        """Get fake counts for all roads."""
        from controller.state_models import Road
        counts_obj = self.fake_gen.next_counts()
        return {
            road.value: getattr(counts_obj, road.value).dict()
            for road in Road
        }
    
    def get_metadata(self) -> Dict:
        """Return fake provider metadata."""
        return {
            "west_source": "fake",
            "camera_ok": False,
            "last_frame_ts": 0.0,
        }


class HybridProvider(RoadProviderBase):
    """
    Hybrid provider: uses YOLO camera for WEST, fake generator for N/E/S.
    
    Single source of truth for controller decision logic.
    """
    
    def __init__(self, fake_provider: FakeProvider, yolo_west_source=None):
        """
        Args:
            fake_provider: FakeProvider instance for N/E/S
            yolo_west_source: YoloWestSource instance (optional, if None uses fake for WEST too)
        """
        self.fake_provider = fake_provider
        self.yolo_west = yolo_west_source
        self.last_log_time = 0.0
        
        if yolo_west_source:
            logger.info("HybridProvider initialized: N/E/S=fake, WEST=YOLO camera")
        else:
            logger.info("HybridProvider initialized: all roads=fake (camera disabled)")
    
    def get_counts(self) -> Dict[str, Dict[str, int]]:
        """
        Get counts: WEST from camera (if ok), else fake. Others always fake.
        """
        from controller.state_models import Road
        fake_counts = self.fake_provider.get_counts()
        
        # Override west_entry if camera is available
        if self.yolo_west:
            try:
                camera_west = self.yolo_west.get_latest_counts()
                if camera_west and isinstance(camera_west, dict) and sum(camera_west.values()) > 0:
                    fake_counts["west_entry"] = camera_west
                    logger.info(f"[PROVIDER] Using CAMERA WEST counts: {camera_west}")
            except Exception as e:
                logger.error(f"[PROVIDER] Failed to get WEST from camera: {e}")
        
        return fake_counts
    
class SumoProvider(RoadProviderBase):
    """
    Provider that reads vehicle counts directly from SUMO.
    Used when we want the AI to respond to simulated traffic.
    """
    
    def __init__(self, sumo_connector):
        """
        Args:
            sumo_connector: SUMOConnector instance
        """
        self.sumo = sumo_connector
        logger.info("SumoProvider initialized (using real SUMO traffic data)")
    
    def get_counts(self) -> Dict[str, Dict[str, int]]:
        """Get counts from SUMO."""
        counts_obj = self.sumo.get_counts()
        from controller.state_models import Road
        return {
            road.value: getattr(counts_obj, road.value).dict()
            for road in Road
        }
    
    def get_metadata(self) -> Dict:
        """Return sumo provider metadata."""
        return {
            "west_source": "sumo",
            "camera_ok": True,
            "last_frame_ts": 0.0,
        }

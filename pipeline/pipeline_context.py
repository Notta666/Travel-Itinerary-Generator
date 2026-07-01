from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import time

@dataclass
class PipelineContext:
    city: str
    days: int
    start_date: str = ""
    preferences: Dict[str, Any] = field(default_factory=dict)
    manual_pois: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    
    # Internal states
    poi_raw: List[Dict] = field(default_factory=list)
    poi_geocoded: List[Dict] = field(default_factory=list)
    poi_enriched: List[Dict] = field(default_factory=list)
    food_recommendations: List[Dict] = field(default_factory=list)
    distance_matrix: Dict[str, Any] = field(default_factory=dict)
    
    # Itinerary results
    itinerary: Optional[List[Dict]] = None
    
    # FlyAI results
    flyai_prices: Dict[str, Any] = field(default_factory=dict)
    
    # Tips & Weather
    travel_tips: Dict[str, Any] = field(default_factory=dict)
    weather: Dict[str, Any] = field(default_factory=dict)
    research_notes: List[Dict] = field(default_factory=list)
    note_contents: List[str] = field(default_factory=list)
    xhs_pois: Dict[str, Any] = field(default_factory=lambda: {"sights": [], "foods": []})
    xhs_sight_names: List[str] = field(default_factory=list)
    xhs_food_data: List[Dict] = field(default_factory=list)
    
    # Multi-city
    multi_cities: List[str] = field(default_factory=list)
    sight_city_map: Dict[str, str] = field(default_factory=dict)
    food_city_map: Dict[str, str] = field(default_factory=dict)
    food_highlights: List[str] = field(default_factory=list)
    overall_note: str = ""
    city_itineraries: Dict[str, Any] = field(default_factory=dict)
    
    # Outputs
    html_path: Optional[str] = None
    report_path: Optional[str] = None
    brochure_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert back to dict for legacy compatibility where needed."""
        return self.__dict__
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PipelineContext':
        """Load from dict for legacy compatibility."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

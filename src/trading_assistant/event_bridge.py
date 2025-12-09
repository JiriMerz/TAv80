"""
Event Bridge - Thread-safe communication between WebSocket and AppDaemon
Sprint 2 implementation with proper queue management and metrics
FIXED VERSION
"""
import queue
from queue import Queue
import threading
from threading import Lock
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class EventBridge:
    """
    Thread-safe event queue between WebSocket and AppDaemon threads
    Prevents race conditions and ensures proper state management
    """
    
    def __init__(self, hass_app):
        self.hass = hass_app
        self.queue = Queue(maxsize=1000)
        self.running = True
        self.metrics = {
            'events_processed': 0,
            'events_dropped': 0,
            'max_queue_depth': 0,
            'last_process_time': None
        }
        self._lock = Lock()
        
        logger.info("EventBridge initialized with queue size 1000")
        
    def push_event(self, event_type: str, data: Dict[str, Any]) -> bool:
        """
        Thread-safe push from WebSocket thread
        Returns False if queue is full
        """
        try:
            self.queue.put_nowait({
                'type': event_type,
                'data': data,
                'timestamp': datetime.now(),
                'thread_id': threading.get_ident()
            })
            
            # Update metrics
            with self._lock:
                current_size = self.queue.qsize()
                if current_size > self.metrics['max_queue_depth']:
                    self.metrics['max_queue_depth'] = current_size
            
            return True
            
        except queue.Full:
            with self._lock:
                self.metrics['events_dropped'] += 1
            logger.warning(f"Event queue full, dropping {event_type}")
            return False
    
    def process_events(self, kwargs=None):
        """
        Process events in AppDaemon context
        Called by run_every() at 1Hz
        """
        processed = 0
        max_batch = 50  # Process max 50 events per cycle
        
        while not self.queue.empty() and processed < max_batch:
            try:
                event = self.queue.get_nowait()
                self._route_event(event)
                processed += 1
                
                with self._lock:
                    self.metrics['events_processed'] += 1
                    self.metrics['last_process_time'] = datetime.now()
                    
            except queue.Empty:
                break
            except Exception as e:
                logger.error(f"Event processing error: {e}")
        
        # Publish metrics if events were processed
        if processed > 0:
            self._publish_metrics()
    
    def _route_event(self, event: Dict):
        """Route events to appropriate handlers"""
        event_type = event['type']
        data = event['data']
        
        try:
            if event_type == 'price_update':
                if hasattr(self.hass, 'handle_price_update'):
                    self.hass.handle_price_update(data)
            elif event_type == 'bar_close':
                if hasattr(self.hass, 'handle_bar_close'):
                    self.hass.handle_bar_close(data)
            elif event_type == 'connection_status':
                if hasattr(self.hass, 'handle_connection_status'):
                    self.hass.handle_connection_status(data)
            else:
                logger.debug(f"Unknown event type: {event_type}")
        except Exception as e:
            logger.error(f"Error routing {event_type}: {e}")
    
    def _publish_metrics(self):
        """Publish queue metrics to HA"""
        try:
            # HA 2025.10.4 has strict validation - use minimal attributes
            self.hass.set_state('sensor.event_queue_metrics',
                state=self.queue.qsize(),
                attributes={
                    'friendly_name': 'Event Queue Metrics'
                }
            )
        except Exception as e:
            # Convert exception to string to avoid iteration issues with ClientResponseError
            # Use debug level as this is not critical for new entities
            logger.debug(f"Failed to publish metrics: {str(e)}")
    
    def get_queue_depth(self) -> int:
        """Get current queue depth"""
        return self.queue.qsize()
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics snapshot"""
        with self._lock:
            return self.metrics.copy()
    
    def stop(self):
        """Stop the event bridge"""
        self.running = False
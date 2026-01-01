"""
Time Synchronization Module
Synchronizes system time with NTP server for accurate timestamps
"""
import logging
import socket
import struct
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class TimeSync:
    """
    Synchronizes system time with NTP server
    Provides accurate UTC time for trading system
    """
    
    NTP_SERVERS = [
        'pool.ntp.org',
        'time.google.com',
        'time.cloudflare.com',
        '0.pool.ntp.org',
        '1.pool.ntp.org'
    ]
    
    NTP_PORT = 123
    NTP_PACKET_FORMAT = "!12I"
    NTP_DELTA = 2208988800  # 1970-01-01 00:00:00 UTC
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.time_offset = 0.0  # Offset v sekundách mezi systémovým a NTP časem
        self.last_sync = None
        self.sync_interval = self.config.get('sync_interval_seconds', 3600)  # Sync každou hodinu
        self.enabled = self.config.get('enable_time_sync', True)
        
        if self.enabled:
            self.sync_time()
        else:
            logger.info("[TIME_SYNC] Time synchronization disabled")
    
    def get_ntp_time(self, server: str = None) -> Optional[Tuple[float, datetime]]:
        """
        Získá čas z NTP serveru
        
        Returns:
            Tuple (timestamp, datetime) nebo None při chybě
        """
        server = server or self.NTP_SERVERS[0]
        
        try:
            # Vytvoř NTP packet
            client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            client.settimeout(5)  # 5 sekund timeout
            
            data = b'\x1b' + 47 * b'\0'
            client.sendto(data, (server, self.NTP_PORT))
            
            data, address = client.recvfrom(1024)
            client.close()
            
            if data:
                unpacked = struct.unpack(self.NTP_PACKET_FORMAT, data[0:struct.calcsize(self.NTP_PACKET_FORMAT)])
                # NTP timestamp je v sekundách od 1900-01-01
                ntp_time = unpacked[10] + float(unpacked[11]) / 2**32
                # Převod na Unix timestamp (sekundy od 1970-01-01)
                unix_time = ntp_time - self.NTP_DELTA
                
                dt = datetime.fromtimestamp(unix_time, tz=timezone.utc)
                return unix_time, dt
                
        except Exception as e:
            logger.warning(f"[TIME_SYNC] Failed to get time from {server}: {e}")
            return None
    
    def sync_time(self) -> bool:
        """
        Synchronizuje čas s NTP serverem
        
        Returns:
            True pokud synchronizace proběhla úspěšně
        """
        if not self.enabled:
            return False
        
        logger.info("[TIME_SYNC] Starting time synchronization...")
        
        # Zkus všechny servery
        for server in self.NTP_SERVERS:
            result = self.get_ntp_time(server)
            if result:
                ntp_timestamp, ntp_datetime = result
                system_timestamp = time.time()
                
                # Vypočti offset
                self.time_offset = ntp_timestamp - system_timestamp
                self.last_sync = datetime.now(timezone.utc)
                
                logger.info(f"[TIME_SYNC] ✅ Synchronized with {server}")
                logger.info(f"[TIME_SYNC]   NTP time: {ntp_datetime.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                logger.info(f"[TIME_SYNC]   System time: {datetime.fromtimestamp(system_timestamp, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
                logger.info(f"[TIME_SYNC]   Offset: {self.time_offset:.3f} seconds")
                
                if abs(self.time_offset) > 60:
                    logger.warning(f"[TIME_SYNC] ⚠️ Large time offset detected ({self.time_offset:.1f}s) - system clock may be incorrect!")
                
                return True
        
        logger.error("[TIME_SYNC] ❌ Failed to synchronize with all NTP servers")
        return False
    
    def now(self) -> datetime:
        """
        Vrací aktuální UTC čas s NTP korekcí
        
        Returns:
            datetime object s timezone.utc
        """
        if not self.enabled or self.time_offset == 0:
            return datetime.now(timezone.utc)
        
        # Přidej offset k systémovému času
        corrected_timestamp = time.time() + self.time_offset
        return datetime.fromtimestamp(corrected_timestamp, tz=timezone.utc)
    
    def should_resync(self) -> bool:
        """
        Kontroluje, zda je potřeba resynchronizace
        
        Returns:
            True pokud je čas na resynchronizaci
        """
        if not self.enabled or not self.last_sync:
            return False
        
        time_since_sync = (datetime.now(timezone.utc) - self.last_sync).total_seconds()
        return time_since_sync >= self.sync_interval
    
    def auto_resync(self):
        """
        Automatická resynchronizace pokud je potřeba
        """
        if self.should_resync():
            self.sync_time()


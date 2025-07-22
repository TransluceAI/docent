'use client';

import React, { createContext, useContext, useState } from 'react';

import socketService from '../services/socketService';

type WebsocketContextType = {
  socketConnected: boolean;
  wsConnect: (collectionId: string) => void;
};

const WebsocketContext = createContext<WebsocketContextType | null>(null);

const WebsocketProvider = ({ children }: { children: React.ReactNode }) => {
  const [socketConnected, setSocketConnected] = useState(false);

  // const socketRef = useRef(false);
  // useEffect(() => {
  //   if (socketRef.current) {
  //     return;
  //   }

  //   socketService.addConnectionStatusListener(setConnected);
  //   socketService.initSocket();
  //   socketRef.current = true;

  //   // TODO(mengk): fix this hack; for now due to StrictMode this is required
  //   // return () => socketService.removeConnectionStatusListener(setConnected);
  // }, []);

  const wsConnect = (collectionId: string) => {
    socketService.addConnectionStatusListener(setSocketConnected);
    socketService.initSocket(collectionId);
  };

  return (
    <WebsocketContext.Provider value={{ socketConnected, wsConnect }}>
      {children}
    </WebsocketContext.Provider>
  );
};

export default WebsocketProvider;

export const useWebsocket = () => {
  const context = useContext(WebsocketContext);
  if (!context) {
    throw new Error('useWebsocket must be used within a WebsocketProvider');
  }
  return context;
};

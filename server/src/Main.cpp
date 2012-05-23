#include <iostream>

#include "../include/swift.h"
#include "../include/DownloadManager.h"
#include "../include/HttpServer.h"

/**
 * Define the InstallHTTPGateway method in httpgw.cpp.
 */
bool InstallHTTPGateway(struct event_base *evbase, swift::Address addr, uint32_t chunk_size, double *maxspeed);

/**
 * Initialise libswift engine.
 */
 int initSwift() {
	swift::Channel::evbase = event_base_new();
	
	evutil_socket_t sock = INVALID_SOCKET;
	swift::Address bindaddress;
	for (int i = 0; i < 10; i++) {
		bindaddress = swift::Address((uint32_t) INADDR_ANY, 0);
		sock = swift::Listen(swift::Address(bindaddress));
		
		if (sock > 0) {
			break;
		}
		
		if (sock == 9) {
			std::cerr << "Could not listen to any socket for swift." << std::endl;
			return -1;
		}
	}
	std::cout << "Listening on port " << swift::BoundAddress(sock).port() << "." << std::endl;
	
	
	// HTTP gateway address for swift to stream.
	swift::Address httpaddr    = swift::Address("127.0.0.1:15000");
	
	//swift::Address httpaddr    = swift::Address("130.161.158.52:15000");
	double maxspeed[2] = {DBL_MAX, DBL_MAX};
	
	// Install the HTTP gateway to stream.
	bool res = InstallHTTPGateway(swift::Channel::evbase, httpaddr, SWIFT_DEFAULT_CHUNK_SIZE, maxspeed);
	
	std::cout << "Initialised swift" << std::endl;
	
	return 0;
}

/**
 * Application main loop.
 */
int main(){
	initSwift();
	
	// Make httpserver loop
	HttpServer::init();
}

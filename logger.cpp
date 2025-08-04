// logger.cpp
#include <iostream>
#include <fstream>
#include <nlohmann/json.hpp>

int main() {
    std::ifstream input("input.json");
    nlohmann::json j;
    input >> j;
    std::cout << "[C++] Received: " << j["value"] << std::endl;
    std::ofstream output("output.json");
    output << "{}";
    return 0;
}

// Explicit fixed plans only. Financial parsing, schedules and closes belong to A.
#define main frozen_scaled_search_a_main
#include "search_a.cpp"
#undef main

int main(int argc, char** argv) {
    try {
        if (argc != 4) throw std::runtime_error("Usage: fixed_plan_probe_a RAW MASKS RECORDS");
        Public p = read_public(argv[1]);
        if (p.k != p.n) throw std::runtime_error("A fixed plans require all public project bits");
        for (int bit = 0; bit < p.n; ++bit)
            if (p.active[bit] != bit) throw std::runtime_error("A fixed plan bits must follow public order");
        auto sparse = compile_sparse(p);
        std::ifstream masks(argv[2]);
        std::string marker; std::getline(masks, marker);
        std::uint64_t count = 0;
        if (marker != "CAPITAL_EXPLICIT_FIXED_MASKS_V1" || !(masks >> count) || count < 1 || count > 256)
            throw std::runtime_error("A requires one to 256 explicit masks");
        std::ofstream output(argv[3], std::ios::binary | std::ios::trunc);
        if (!output) throw std::runtime_error("Cannot create A fixed-plan records");
        for (std::uint64_t ordinal = 0; ordinal < count; ++ordinal) {
            std::uint64_t raw = 0;
            if (!(masks >> raw) || raw >= (std::uint64_t(1) << p.n))
                throw std::runtime_error("A missing or out-of-range explicit mask");
            auto mask = static_cast<std::uint32_t>(raw);
            Flows flow{};
            for (int bit = 0; bit < p.n; ++bit) if (mask & (std::uint32_t(1) << bit))
                for (auto [at, amount] : sparse[bit]) flow[at] = narrow(W(flow[at]) + amount);
            std::array<I, S> values{}; std::uint32_t flags = 0;
            for (int scenario = 0; scenario < S; ++scenario) {
                values[scenario] = close_scenario(p, flow, scenario);
                if (values[scenario] != ABSENT) flags |= std::uint32_t(1) << scenario;
            }
            char record[32]; u32(record, mask); u32(record + 4, flags);
            for (int scenario = 0; scenario < S; ++scenario) i64(record + 8 + 8 * scenario, values[scenario]);
            output.write(record, sizeof record);
            if (!output) throw std::runtime_error("A incomplete fixed-plan write");
        }
        std::string extra;
        if (masks >> extra) throw std::runtime_error("A unexpected extra explicit mask");
        output.close();
        if (!output) throw std::runtime_error("A fixed-plan output did not close");
        std::cout << "{\"kind\":\"scaled_fixed_plan_A_native\",\"plan_count\":" << count
                  << ",\"scenario_evaluations\":" << count * S
                  << ",\"enumeration_performed\":false,\"ranking_performed\":false}\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}

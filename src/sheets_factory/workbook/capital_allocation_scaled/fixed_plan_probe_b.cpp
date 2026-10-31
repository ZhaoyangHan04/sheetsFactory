// Explicit fixed plans only. Financial parsing, schedules and closes belong to B.
#define main frozen_scaled_search_b_main
#include "search_b.cpp"
#undef main

int main(int argc, char** argv) {
    try {
        if (argc != 4) throw std::runtime_error("Usage: fixed_plan_probe_b RAW MASKS RECORDS");
        std::ifstream raw(argv[1]);
        if (!raw) throw std::runtime_error("Cannot read B fixed-plan primitives");
        Public p = read_public(raw);
        if (p.dimensions != p.count) throw std::runtime_error("B fixed plans require all public project bits");
        for (int bit = 0; bit < p.count; ++bit)
            if (p.active[bit] != bit) throw std::runtime_error("B fixed plan bits must follow public order");
        std::vector<PortfolioFlow> projects;
        for (int index = 0; index < p.count; ++index) projects.push_back(project_flows(p, index));
        std::ifstream masks(argv[2]);
        std::string marker; std::getline(masks, marker);
        std::uint64_t count = 0;
        if (marker != "CAPITAL_EXPLICIT_FIXED_MASKS_V1" || !(masks >> count) || count < 1 || count > 256)
            throw std::runtime_error("B requires one to 256 explicit masks");
        std::ofstream output(argv[3], std::ios::binary | std::ios::trunc);
        if (!output) throw std::runtime_error("Cannot create B fixed-plan records");
        std::uint64_t evaluated_years = 0;
        for (std::uint64_t ordinal = 0; ordinal < count; ++ordinal) {
            std::uint64_t raw_mask = 0;
            if (!(masks >> raw_mask) || raw_mask >= (std::uint64_t(1) << p.count))
                throw std::runtime_error("B missing or out-of-range explicit mask");
            auto mask = static_cast<std::uint32_t>(raw_mask);
            PortfolioFlow total{}, zero{};
            for (int bit = 0; bit < p.count; ++bit) if (mask & (std::uint32_t(1) << bit))
                for (int scenario = 0; scenario < NS; ++scenario)
                    for (int year = 0; year < NY; ++year)
                        for (int field = 0; field < NF; ++field)
                            total[scenario][year][field] = integer(W(total[scenario][year][field]) + projects[bit][scenario][year][field]);
            std::array<Outcome, NS> outcomes{}; std::uint32_t flags = 0;
            for (int scenario = 0; scenario < NS; ++scenario) {
                outcomes[scenario] = close(p, scenario, total, zero, evaluated_years);
                if (outcomes[scenario].feasible) flags |= std::uint32_t(1) << scenario;
            }
            std::vector<char> record; record.reserve(32); u32(record, mask); u32(record, flags);
            for (const auto& result : outcomes) i64(record, result.npv);
            output.write(record.data(), static_cast<std::streamsize>(record.size()));
            if (!output) throw std::runtime_error("B incomplete fixed-plan write");
        }
        std::string extra;
        if (masks >> extra) throw std::runtime_error("B unexpected extra explicit mask");
        output.close();
        if (!output) throw std::runtime_error("B fixed-plan output did not close");
        std::cout << "{\"kind\":\"scaled_fixed_plan_B_native\",\"plan_count\":" << count
                  << ",\"scenario_evaluations\":" << count * NS
                  << ",\"scenario_year_evaluations\":" << evaluated_years
                  << ",\"enumeration_performed\":false,\"ranking_performed\":false}\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}

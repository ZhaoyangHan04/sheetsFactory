// Recompute only supplied masks with one unchanged, opposite financial core.
// No search scheduler, bounds, ranking or optimum assertion is invoked.
#if defined(CHECK_FINANCIAL_A) == defined(CHECK_FINANCIAL_B)
#error Define exactly one checking financial core.
#endif
#define main unused_frozen_financial_main
#ifdef CHECK_FINANCIAL_A
#include "../capital_allocation_scaled/search_a.cpp"
#else
#include "../capital_allocation_scaled/search_b.cpp"
#endif
#undef main
#include <chrono>
#include "public_reader.inc"

struct CheckStopped:std::runtime_error {using std::runtime_error::runtime_error;};
static std::uint64_t check_positive(const char* text) {
    std::string s(text);
    if(s.empty()||s.size()>18||s[0]=='0'||std::any_of(s.begin(),s.end(),[](char c){return c<'0'||c>'9';}))
        throw std::runtime_error("Canonical positive checker limit required");
    return std::stoull(s);
}
static std::uint64_t decode64(const char* b) {
    std::uint64_t value=0;for(int i=0;i<8;++i)value|=std::uint64_t(static_cast<unsigned char>(b[i]))<<(8*i);return value;
}
static void encode64(char* b,std::uint64_t value) {for(int i=0;i<8;++i)b[i]=char((value>>(8*i))&255);}

int main(int argc,char** argv) {
    try {
        const auto began=std::chrono::steady_clock::now();
        if(argc!=8)throw std::runtime_error("Expected raw public, mask stream, outcomes, summary, expected rows, mask cap, millisecond cap");
        const auto expected=check_positive(argv[5]),cap=check_positive(argv[6]),ms=check_positive(argv[7]);
        // Compare elapsed milliseconds directly: converting an 18-digit limit
        // to the clock's nanoseconds would overflow its signed duration.
        auto deadline=[&](){if(std::uint64_t(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-began).count())>=ms)throw CheckStopped("elapsed_limit");};
        std::uint64_t rows=0,forwards=0,scenario_calls=0,years=0;
        bool complete=false;std::string stop;
        std::ifstream masks(argv[2],std::ios::binary);if(!masks)throw std::runtime_error("Cannot open mask stream");
        std::ofstream output(argv[3],std::ios::binary|std::ios::trunc);if(!output)throw std::runtime_error("Cannot create outcomes");
        try {
            if(expected>cap)throw CheckStopped("mask_limit");
            deadline();
#ifdef CHECK_FINANCIAL_A
            const Public p=sparse_public(argv[1]);const int n=p.n;
            const auto deltas=compile_sparse(p);Flows current{};
#else
            const Public p=sparse_public_b(argv[1]);const int n=p.count;
            struct Delta {int s,y,f;I amount;};std::vector<std::vector<Delta>> deltas;
            for(int j=0;j<n;++j){auto flow=project_flows(p,j);std::vector<Delta> row;
                for(int s=0;s<NS;++s)for(int y=0;y<NY;++y)for(int f=0;f<NF;++f)
                    if(flow[s][y][f])row.push_back({s,y,f,flow[s][y][f]});deltas.push_back(std::move(row));}
            PortfolioFlow current{},zero{};
#endif
            deadline();std::uint64_t previous=0;
            while(rows<expected) {
                deadline();if(forwards>=cap)throw CheckStopped("mask_limit");
                char input[8];masks.read(input,8);if(masks.gcount()!=8)throw CheckStopped("truncated_masks");
                const auto mask=decode64(input);if(mask>=(std::uint64_t(1)<<n))throw CheckStopped("mask_outside_dimension");
                std::uint64_t changed=mask^previous;
                while(changed) {const int j=__builtin_ctzll(changed);changed&=changed-1;const int direction=(mask&(std::uint64_t(1)<<j))?1:-1;
#ifdef CHECK_FINANCIAL_A
                    for(auto [at,amount]:deltas[j])current[at]=narrow(W(current[at])+W(direction)*amount);
#else
                    for(const auto& d:deltas[j])current[d.s][d.y][d.f]=integer(W(current[d.s][d.y][d.f])+W(direction)*d.amount);
#endif
                }
                previous=mask;std::array<I,3> npv{};std::uint64_t flags=0;
                for(int s=0;s<3;++s) {
                    ++scenario_calls;
#ifdef CHECK_FINANCIAL_A
                    npv[s]=close_scenario(p,current,s);
#else
                    auto result=close(p,s,current,zero,years);npv[s]=result.npv;
                    if(result.feasible!=(npv[s]!=std::numeric_limits<I>::min()))throw std::runtime_error("Inconsistent frozen B outcome");
#endif
                    if(npv[s]!=std::numeric_limits<I>::min())flags|=std::uint64_t(1)<<s;
                }
                ++forwards;deadline();char record[40];encode64(record,mask);encode64(record+8,flags);
                for(int s=0;s<3;++s)encode64(record+16+s*8,static_cast<std::uint64_t>(npv[s]));
                output.write(record,40);if(!output)throw std::runtime_error("Outcome write failed");++rows;deadline();
            }
            char extra;if(masks.get(extra))throw CheckStopped("trailing_masks");
            if(!masks.eof())throw std::runtime_error("Mask input read failed");deadline();
            output.close();if(!output)throw std::runtime_error("Outcome close failed");deadline();complete=true;
        } catch(const CheckStopped& e) {stop=e.what();}
          catch(const std::exception& e) {stop="execution_error";std::cerr<<e.what()<<'\n';}
        if(output.is_open())output.close();
        if(!output){complete=false;stop="output_failure";}
        // A slow final flush must never turn a deadline-exhausted run into success.
        try{deadline();}catch(const CheckStopped& e){complete=false;stop=e.what();}
        auto emit_summary=[&](){
        const auto elapsed=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-began).count();
        std::ofstream summary(argv[4]);if(!summary)throw std::runtime_error("Cannot write checker summary");
        summary<<"{\"kind\":\"sparse_capital_supplied_masks_native\",\"version\":1,\"checking_financial_core\":\""
#ifdef CHECK_FINANCIAL_A
            <<"A"
#else
            <<"B"
#endif
            <<"\",\"complete\":"<<(complete?"true":"false")<<",\"status\":\""<<(complete?"completed":"incomplete")
            <<"\",\"stop_reason\":\""<<stop<<"\",\"expected_rows\":\""<<expected<<"\",\"row_count\":\""<<rows
            <<"\",\"financial_forward_calls\":\""<<forwards<<"\",\"scenario_forward_calls\":\""<<scenario_calls
            <<"\",\"actual_scenario_year_states\":"
#ifdef CHECK_FINANCIAL_A
            <<"null"
#else
            <<'"'<<years<<'"'
#endif
            <<",\"max_masks\":\""<<cap<<"\",\"max_ms\":\""<<ms<<"\",\"elapsed_nanoseconds\":\""<<elapsed
            <<"\",\"optimizer_runs\":0,\"optimum_certified\":false,\"source_quality_or_difficulty_certified\":false}\n";
        summary.close();if(!summary)throw std::runtime_error("Checker summary close failed");};
        emit_summary();
        // Metadata finalization is part of the native cap too. If it blocks,
        // retain an explicitly incomplete final summary and a nonzero exit.
        try{deadline();}catch(const CheckStopped& e){complete=false;stop=e.what();emit_summary();}
        return complete?0:2;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}

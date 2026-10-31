// Independent B financial translation unit; no A reader, flows or answers.
#define main capital_scaled_frozen_main_b
#include "../capital_allocation_scaled/search_b.cpp"
#undef main
#include <chrono>
#include <iomanip>
#include <queue>
#include <sstream>

static I bounded(std::istream& in,I low,I high){I n=number(in);if(n<low||n>high)throw std::runtime_error("B sparse primitive outside bounds");return n;}
static Series raw_series(std::istream& in,I low,I high){Series a{};for(I& n:a)n=bounded(in,low,high);return a;}
static Public sparse_public_b(const char* path){
    std::ifstream in(path);std::string magic;std::getline(in,magic);
    if(!in||magic!="CAPITAL_SPARSE_B_RAW_V1")throw std::runtime_error("Wrong independent sparse B raw wire");
    Public p{};p.count=int(bounded(in,40,56));if(p.count!=40&&p.count!=48&&p.count!=56)throw std::runtime_error("Wrong sparse B dimension");
    p.dimensions=p.count;for(int j=0;j<p.count;++j)p.active.push_back(j);
    p.opening=bounded(in,0,100000000000LL);p.minimum=bounded(in,0,p.opening);
    p.commitment=bounded(in,0,100000000000LL);p.facility=bounded(in,0,100000000000LL);
    p.advance=bounded(in,0,SCALE);p.tax=bounded(in,0,SCALE);p.carry=int(bounded(in,1,20));
    p.discount=raw_series(in,1,SCALE);for(int y=1;y<NY;++y)if(p.discount[y]>p.discount[y-1])throw std::runtime_error("Increasing B discount");
    for(int j=0;j<p.count;++j){
        Project q{};q.commission=int(bounded(in,0,18));q.sale_year=int(bounded(in,q.commission+1,19));
        q.cost=bounded(in,1,1000000000LL);q.life=int(bounded(in,1,20));q.sale_price=bounded(in,0,1000000000LL);
        q.revenue=raw_series(in,0,1000000000LL);q.expense=raw_series(in,0,1000000000LL);
        for(int y=0;y<NY;++y)if((y<=q.commission||y>q.sale_year)&&(q.revenue[y]||q.expense[y]))throw std::runtime_error("B operations outside period");
        p.projects.push_back(q);
    }
    for(auto& s:p.scenarios){s.sales=raw_series(in,0,3*SCALE);s.costs=raw_series(in,0,3*SCALE);s.valuation=raw_series(in,0,3*SCALE);
        s.exit_price=raw_series(in,0,3*SCALE);s.interest=raw_series(in,0,SCALE);s.haircut=raw_series(in,0,SCALE);}
    std::string extra;if(in>>extra)throw std::runtime_error("Trailing independent B primitive");return p;
}
struct BRow{std::string id;I capacity;std::vector<I> weight;};
struct BEnvelope{std::vector<int> order;std::array<I,NS> constant{};std::vector<std::array<I,NS>> gain;std::vector<BRow> cuts;};
static BEnvelope sparse_envelope_b(const char* path,int n){
    std::ifstream in(path);std::string magic;std::getline(in,magic);
    if(!in||magic!="CAPITAL_SPARSE_B_SAFE_BOUND_V1"||bounded(in,n,n)!=n)throw std::runtime_error("Wrong B safe bound wire");
    BEnvelope b;std::vector<bool> seen(n,false);for(int j=0;j<n;++j){int k=int(bounded(in,0,n-1));if(seen[k])throw std::runtime_error("Repeated B branch index");seen[k]=true;b.order.push_back(k);}
    const I limit=I(1)<<62;auto scalar=[&](){return bounded(in,-limit+1,limit-1);};
    for(I& x:b.constant)x=scalar();for(int j=0;j<n;++j){std::array<I,NS>a{};for(I& x:a)x=scalar();b.gain.push_back(a);}
    bounded(in,NS*NY*2,NS*NY*2);
    for(int k=0;k<NS*NY*2;++k){BRow c;in>>c.id;
        std::string expected="S0"+std::to_string(k/(NY*2)+1)+"."+std::to_string(2024+(k/2)%NY)+(k%2?".collateral":".facility");
        if(c.id!=expected)throw std::runtime_error("B necessary cut order differs");
        c.capacity=scalar();W magnitude=c.capacity<0?-W(c.capacity):W(c.capacity);
        for(int j=0;j<n;++j){I x=scalar();c.weight.push_back(x);magnitude+=x<0?-W(x):W(x);}
        if(magnitude>=limit)throw std::runtime_error("B cut aggregate exceeds signed envelope");b.cuts.push_back(c);
    }
    for(int s=0;s<NS;++s){W sum=b.constant[s]<0?-W(b.constant[s]):W(b.constant[s]);for(auto a:b.gain)sum+=a[s]<0?-W(a[s]):W(a[s]);
        if(sum>=limit)throw std::runtime_error("B objective aggregate exceeds signed envelope");}
    std::string extra;if(in>>extra)throw std::runtime_error("Trailing B bound wire");return b;
}
static std::string mask_text_b(std::uint64_t mask){std::ostringstream out;out<<"0x"<<std::hex<<std::setw(16)<<std::setfill('0')<<mask;return out.str();}
struct BRank{I objective;std::uint64_t mask;std::array<I,NS> npv;};
struct BRegion{int depth=0;std::uint64_t known=0,mask=0;std::array<I,NS> upper{};std::array<I,NS*NY*2> lower{};I priority=0;};
struct BPriority{bool operator()(const BRegion&a,const BRegion&b)const{
    if(a.priority!=b.priority)return a.priority<b.priority;
    if(a.depth!=b.depth)return a.depth<b.depth;
    return a.mask<b.mask;
}};
struct BStopped:std::runtime_error{using std::runtime_error::runtime_error;};
struct BSearch{
    const Public& p;const BEnvelope& b;std::chrono::steady_clock::time_point start;
    std::uint64_t node_cap,ms_cap,frontier_cap,nodes=0,forwards=0,seed_forwards=0,years=0,regions=0,covered=0,bounds_pruned=0,infeasible=0,peak_frontier=0;
    std::vector<PortfolioFlow> projects;std::vector<BRank> top;std::ofstream wire;std::string phase="best_upper_first";
    BSearch(const Public& pub,const BEnvelope& envelope,std::chrono::steady_clock::time_point began,std::uint64_t nc,std::uint64_t mc,std::uint64_t fc,const char* output)
      :p(pub),b(envelope),start(began),node_cap(nc),ms_cap(mc),frontier_cap(fc),wire(output){
        if(!wire)throw std::runtime_error("Cannot create B sparse partition");for(int j=0;j<p.count;++j)projects.push_back(project_flows(p,j));
    }
    void deadline(){if(std::uint64_t(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count())>=ms_cap)throw BStopped("elapsed_limit");}
    void visit(){if(nodes>=node_cap)throw BStopped("node_limit");++nodes;if(nodes==1||nodes%1024==0)deadline();}
    void frontier(std::size_t size){if(size>frontier_cap)throw BStopped("frontier_limit");peak_frontier=std::max<std::uint64_t>(peak_frontier,size);}
    BRegion root(){BRegion r;r.upper=b.constant;
        for(auto a:b.gain)for(int s=0;s<NS;++s)r.upper[s]=integer(W(r.upper[s])+std::max<I>(0,a[s]));
        for(std::size_t k=0;k<b.cuts.size();++k)for(I w:b.cuts[k].weight)r.lower[k]=integer(W(r.lower[k])+std::min<I>(0,w));
        r.priority=*std::min_element(r.upper.begin(),r.upper.end());return r;
    }
    BRegion child(const BRegion& parent,int bit){BRegion r=parent;int j=b.order[parent.depth];++r.depth;r.known|=std::uint64_t(1)<<j;if(bit)r.mask|=std::uint64_t(1)<<j;
        for(int s=0;s<NS;++s)r.upper[s]=integer(W(r.upper[s])+W(bit)*b.gain[j][s]-std::max<I>(0,b.gain[j][s]));
        for(std::size_t k=0;k<b.cuts.size();++k)r.lower[k]=integer(W(r.lower[k])+W(bit)*b.cuts[k].weight[j]-std::min<I>(0,b.cuts[k].weight[j]));
        r.priority=*std::min_element(r.upper.begin(),r.upper.end());return r;
    }
    int contradiction(const BRegion&r){for(std::size_t k=0;k<b.cuts.size();++k)if(r.lower[k]>b.cuts[k].capacity)return int(k);return -1;}
    std::array<I,NS> forward(std::uint64_t mask){deadline();PortfolioFlow flow{},zero{};
        for(int j=0;j<p.count;++j)if(mask&(std::uint64_t(1)<<j))for(int s=0;s<NS;++s)for(int y=0;y<NY;++y)for(int f=0;f<NF;++f)
            flow[s][y][f]=integer(W(flow[s][y][f])+projects[j][s][y][f]);
        std::array<I,NS> result{};for(int s=0;s<NS;++s){auto row=close(p,s,flow,zero,years);result[s]=row.npv;}
        ++forwards;deadline();return result;
    }
    void rank(std::uint64_t mask,const std::array<I,NS>& npv){
        if(std::any_of(npv.begin(),npv.end(),[](I x){return x==std::numeric_limits<I>::min();}))return;
        if(std::any_of(top.begin(),top.end(),[&](const BRank&r){return r.mask==mask;}))return;
        top.push_back({*std::min_element(npv.begin(),npv.end()),mask,npv});
        std::sort(top.begin(),top.end(),[](const BRank&a,const BRank&b){return a.objective>b.objective||(a.objective==b.objective&&a.mask<b.mask);});
        if(top.size()>2)top.resize(2);
    }
    void seed(){rank(0,forward(0));++seed_forwards;auto all=(std::uint64_t(1)<<p.count)-1;rank(all,forward(all));++seed_forwards;
        for(int j=p.count-1;j>=0;--j){auto mask=std::uint64_t(1)<<j;rank(mask,forward(mask));++seed_forwards;}deadline();}
    void optimise(){std::priority_queue<BRegion,std::vector<BRegion>,BPriority> pending;frontier(1);pending.push(root());
        while(!pending.empty()){
            auto r=pending.top();pending.pop();visit();
            if(contradiction(r)>=0)continue;
            if(top.size()==2&&r.priority<=top[1].objective)continue;
            if(r.depth==p.count){rank(r.mask,forward(r.mask));continue;}
            frontier(pending.size()+1);pending.push(child(r,0));frontier(pending.size()+1);pending.push(child(r,1));
        }deadline();
    }
    std::string prefix(const BRegion&r){std::string out;for(int d=0;d<r.depth;++d)out.push_back((r.mask&(std::uint64_t(1)<<b.order[d]))?'1':'0');return out;}
    void emit(const BRegion&r,char kind,int cut=-1,const std::array<I,NS>*npv=nullptr){
        auto text=prefix(r);wire<<kind<<'\t'<<(text.empty()?"-":text);
        if(kind=='I'){wire<<'\t'<<b.cuts[cut].id;++infeasible;}
        if(kind=='B'){wire<<'\t'<<r.priority;++bounds_pruned;}
        if(kind=='L'){wire<<'\t'<<mask_text_b(r.mask);unsigned flags=0;for(int s=0;s<NS;++s)if((*npv)[s]!=std::numeric_limits<I>::min())flags|=1u<<s;
            wire<<'\t'<<flags;for(I value:*npv){wire<<'\t';if(value==std::numeric_limits<I>::min())wire<<"null";else wire<<value;}}
        wire<<'\n';if(!wire)throw std::runtime_error("B partition write failed");++regions;covered+=std::uint64_t(1)<<(p.count-r.depth);
    }
    void prove(){phase="ordered_partition";deadline();std::vector<BRegion> stack{root()};frontier(stack.size());
        while(!stack.empty()){
            auto r=stack.back();stack.pop_back();visit();bool force=std::any_of(top.begin(),top.end(),[&](const BRank&row){return (row.mask&r.known)==r.mask;});
            int cut=contradiction(r);if(cut>=0&&!force){emit(r,'I',cut);continue;}
            if(r.priority<=top[1].objective&&!force){emit(r,'B');continue;}
            if(r.depth==p.count){auto npv=forward(r.mask);emit(r,'L',-1,&npv);continue;}
            frontier(stack.size()+1);stack.push_back(child(r,1));frontier(stack.size()+1);stack.push_back(child(r,0));
        }deadline();wire.close();deadline();if(!wire)throw std::runtime_error("B partition close failed");
    }
};
static std::uint64_t positive_b(const char*text){std::string s(text);if(s.empty()||s.size()>18||s[0]=='0'||std::any_of(s.begin(),s.end(),[](char c){return c<'0'||c>'9';}))throw std::runtime_error("Canonical positive B limit required");return std::stoull(s);}
static void rank_json_b(std::ostream&out,const BRank&r){out<<"{\"mask_hex\":\""<<mask_text_b(r.mask)<<"\",\"objective_pence\":\""<<r.objective<<"\",\"scenario_npvs_pence\":{\"S01\":\""<<r.npv[0]<<"\",\"S02\":\""<<r.npv[1]<<"\",\"S03\":\""<<r.npv[2]<<"\"}}";}
int main(int argc,char**argv){try{
    auto began=std::chrono::steady_clock::now();if(argc!=8)throw std::runtime_error("B expects public/bounds/partition/summary/max_nodes/max_ms/max_frontier");
    auto p=sparse_public_b(argv[1]);auto b=sparse_envelope_b(argv[2],p.count);
    BSearch search(p,b,began,positive_b(argv[5]),positive_b(argv[6]),positive_b(argv[7]),argv[3]);bool complete=false;std::string stop;
    try{search.deadline();search.seed();search.deadline();search.optimise();search.deadline();
        if(search.top.size()<2)throw BStopped("fewer_than_two_feasible_plans");search.prove();search.deadline();
        if(search.covered!=(std::uint64_t(1)<<p.count))throw std::runtime_error("B output coverage incomplete");complete=true;
    }catch(const BStopped&e){stop=e.what();if(search.wire.is_open())search.wire.close();}
    std::ofstream out(argv[4]);if(!out)throw std::runtime_error("Cannot create B summary");
    out<<"{\"kind\":\"sparse_capital_B_intermediate_search\",\"version\":1,\"status\":\""<<(complete?"completed_intermediate":"incomplete")<<"\",\"project_count\":"<<p.count
       <<",\"combinatorial_plan_count\":\""<<(std::uint64_t(1)<<p.count)<<"\",\"visited_nodes\":\""<<search.nodes<<"\",\"forward_evaluations\":\""<<search.forwards
       <<"\",\"seed_forward_evaluations\":\""<<search.seed_forwards<<"\",\"scenario_year_evaluations\":\""<<search.years<<"\",\"emitted_regions\":\""<<search.regions
       <<"\",\"covered_plan_count\":\""<<search.covered<<"\",\"bound_regions\":\""<<search.bounds_pruned<<"\",\"infeasible_regions\":\""<<search.infeasible
       <<"\",\"peak_frontier\":\""<<search.peak_frontier<<"\",\"max_nodes\":\""<<search.node_cap<<"\",\"max_ms\":\""<<search.ms_cap<<"\",\"max_frontier\":\""<<search.frontier_cap
       <<"\",\"best\":";if(search.top.empty())out<<"null";else rank_json_b(out,search.top[0]);out<<",\"runnerup\":";if(search.top.size()<2)out<<"null";else rank_json_b(out,search.top[1]);
    out<<",\"gap_pence\":";if(search.top.size()<2)out<<"null";else out<<'"'<<integer(W(search.top[0].objective)-search.top[1].objective)<<'"';
    out<<",\"partition_coverage_complete\":"<<(complete?"true":"false")<<",\"stop_reason\":\""<<stop<<"\",\"shared_public_exact_bound_policy\":true,\"semantic_certificate_verified\":false,\"independent_comparison_completed\":false,\"source_quality_or_difficulty_certified\":false}\n";
    out.close();if(!out)throw std::runtime_error("B summary write incomplete");return complete?0:2;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}

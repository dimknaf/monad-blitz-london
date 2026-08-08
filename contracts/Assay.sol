// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Assay — agents get paid to judge reality, and get slashed when they're wrong.
/// @notice Claims carry an immutable hash of their resolution spec. Deterministic claims settle
///         from a filing; judgement claims settle from a panel of bonded research agents.
contract Assay {
    enum Status { Open, ResolvedYes, ResolvedNo, Void }

    struct Claim {
        bytes32 specHash;      // hash of the full resolution spec — the question is immutable
        string  specURI;       // where to read that spec
        address opener;
        uint64  resolveAfter;  // no finalize before this
        uint8   quorum;        // attestations needed; 2 so one timeout can't stall a demo
        uint256 poolYes;
        uint256 poolNo;
        Status  status;
        string  evidence;      // SEC accession for deterministic, or set at finalize
    }

    struct Attestation {
        address agent;
        bool    verdict;
        uint256 bond;
        string  evidenceURI;
    }

    /// @notice Stake an agent posts with a verdict. Set at deploy, not hardcoded.
    uint256 public immutable BOND;

    constructor(uint256 bond) {
        BOND = bond;
    }

    Claim[] public claims;
    mapping(uint256 => Attestation[]) public attestations;
    mapping(uint256 => mapping(address => bool))    public hasAttested;
    mapping(uint256 => mapping(address => uint256)) public stakeYes;
    mapping(uint256 => mapping(address => uint256)) public stakeNo;
    mapping(uint256 => mapping(address => bool))    public claimed;
    mapping(address => uint256) public credits; // pull-payment

    event ClaimOpened(uint256 indexed id, bytes32 specHash, string specURI, uint8 quorum);
    event Staked(uint256 indexed id, address indexed who, bool side, uint256 amount);
    event Attested(uint256 indexed id, address indexed agent, bool verdict, string evidenceURI);
    event Finalized(uint256 indexed id, Status status, uint256 yes, uint256 no);
    event Slashed(uint256 indexed id, address indexed agent, uint256 amount);

    error NotOpen();
    error AlreadyAttested();
    error BadBond();
    error TooEarly();
    error NoQuorum();
    error NotOpener();
    error NothingToClaim();

    // ---------------------------------------------------------------- claims

    function openClaim(bytes32 specHash, string calldata specURI, uint64 resolveAfter, uint8 quorum)
        external
        returns (uint256 id)
    {
        id = claims.length;
        claims.push(Claim({
            specHash: specHash,
            specURI: specURI,
            opener: msg.sender,
            resolveAfter: resolveAfter,
            quorum: quorum == 0 ? 1 : quorum,
            poolYes: 0,
            poolNo: 0,
            status: Status.Open,
            evidence: ""
        }));
        emit ClaimOpened(id, specHash, specURI, quorum);
    }

    function stake(uint256 id, bool side) external payable {
        Claim storage c = claims[id];
        if (c.status != Status.Open) revert NotOpen();
        if (msg.value == 0) revert BadBond();
        if (side) { c.poolYes += msg.value; stakeYes[id][msg.sender] += msg.value; }
        else      { c.poolNo  += msg.value; stakeNo[id][msg.sender]  += msg.value; }
        emit Staked(id, msg.sender, side, msg.value);
    }

    // ----------------------------------------------------------- attestation

    function attest(uint256 id, bool verdict, string calldata evidenceURI) external payable {
        Claim storage c = claims[id];
        if (c.status != Status.Open) revert NotOpen();          // late attestation is a live race
        if (hasAttested[id][msg.sender]) revert AlreadyAttested();
        if (msg.value != BOND) revert BadBond();
        hasAttested[id][msg.sender] = true;
        attestations[id].push(Attestation(msg.sender, verdict, msg.value, evidenceURI));
        emit Attested(id, msg.sender, verdict, evidenceURI);
    }

    /// @notice Tally the panel. Minority bonds are redistributed to the majority.
    function finalize(uint256 id) external {
        Claim storage c = claims[id];
        if (c.status != Status.Open) revert NotOpen();
        if (block.timestamp < c.resolveAfter) revert TooEarly(); // >= / < only: Monad timestamps repeat
        Attestation[] storage a = attestations[id];
        if (a.length < c.quorum) revert NoQuorum();

        uint256 yes;
        for (uint256 i; i < a.length; ++i) { if (a[i].verdict) ++yes; }
        uint256 no = a.length - yes;

        if (yes == no) {                       // tie -> void, every bond refunded, nobody slashed
            c.status = Status.Void;
            for (uint256 i; i < a.length; ++i) credits[a[i].agent] += a[i].bond;
            emit Finalized(id, Status.Void, yes, no);
            return;
        }

        bool outcome = yes > no;
        c.status = outcome ? Status.ResolvedYes : Status.ResolvedNo;

        uint256 slashed;
        for (uint256 i; i < a.length; ++i) {
            if (a[i].verdict != outcome) { slashed += a[i].bond; emit Slashed(id, a[i].agent, a[i].bond); }
        }
        uint256 winners = outcome ? yes : no;
        for (uint256 i; i < a.length; ++i) {
            if (a[i].verdict == outcome) credits[a[i].agent] += a[i].bond + slashed / winners;
        }
        emit Finalized(id, c.status, yes, no);
    }

    /// @notice Deterministic settlement — no panel. evidenceURI carries the SEC accession number.
    function settleDeterministic(uint256 id, bool outcome, string calldata evidenceURI) external {
        Claim storage c = claims[id];
        if (c.status != Status.Open) revert NotOpen();          // cannot double-settle
        if (msg.sender != c.opener) revert NotOpener();
        c.status = outcome ? Status.ResolvedYes : Status.ResolvedNo;
        c.evidence = evidenceURI;
        emit Finalized(id, c.status, outcome ? 1 : 0, outcome ? 0 : 1);
    }

    // -------------------------------------------------------------- payouts

    /// @notice Winners withdraw their share of the losing pool. Void refunds own stake.
    function claim(uint256 id) external {
        Claim storage c = claims[id];
        if (c.status == Status.Open) revert NotOpen();
        if (claimed[id][msg.sender]) revert NothingToClaim();
        claimed[id][msg.sender] = true;

        uint256 mine = stakeYes[id][msg.sender] + stakeNo[id][msg.sender];
        uint256 owed;

        if (c.status == Status.Void) {
            owed = mine;                                        // straight refund
        } else if (c.status == Status.ResolvedYes) {
            uint256 s = stakeYes[id][msg.sender];
            owed = c.poolYes == 0 ? mine : s + (s * c.poolNo) / c.poolYes;
        } else {
            uint256 s = stakeNo[id][msg.sender];
            owed = c.poolNo == 0 ? mine : s + (s * c.poolYes) / c.poolNo;
        }
        if (owed == 0) revert NothingToClaim();
        credits[msg.sender] += owed;
    }

    function withdraw() external {
        uint256 amount = credits[msg.sender];
        if (amount == 0) revert NothingToClaim();
        credits[msg.sender] = 0;                                // effects before interaction
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
    }

    // ----------------------------------------------------------------- views

    /// @notice Implied probability of YES, 1e18 = 100%. Unstaked reads 50/50, never divides by zero.
    function impliedYes(uint256 id) external view returns (uint256) {
        Claim storage c = claims[id];
        uint256 total = c.poolYes + c.poolNo;
        if (total == 0) return 0.5e18;
        return (c.poolYes * 1e18) / total;
    }

    function claimCount() external view returns (uint256) { return claims.length; }

    function attestationCount(uint256 id) external view returns (uint256) {
        return attestations[id].length;
    }
}

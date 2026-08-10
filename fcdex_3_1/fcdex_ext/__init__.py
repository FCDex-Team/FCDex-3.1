from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


async def setup(bot: "BallsDexBot"):
    from fcdex_3_1.fcdex_ext.achievement_cog import AchievementCog
    from fcdex_3_1.fcdex_ext.battle_cog import BattleCog
    from fcdex_3_1.fcdex_ext.craft_cog import CraftCog
    from fcdex_3_1.fcdex_ext.fcdex_cog import FcdexCog
    from fcdex_3_1.fcdex_ext.match_cog import MatchCog
    from fcdex_3_1.fcdex_ext.merge_cog import MergeCog
    from fcdex_3_1.fcdex_ext.merge_special import bootstrap_merge_specials
    from fcdex_3_1.fcdex_ext.pack_cog import PackCog
    from fcdex_3_1.fcdex_ext.tournament_cog import TournamentCog

    await bootstrap_merge_specials(bot)
    await bot.add_cog(FcdexCog(bot))
    await bot.add_cog(BattleCog(bot))
    await bot.add_cog(MatchCog(bot))
    await bot.add_cog(MergeCog(bot))
    await bot.add_cog(CraftCog(bot))
    await bot.add_cog(PackCog(bot))
    await bot.add_cog(AchievementCog(bot))
    await bot.add_cog(TournamentCog(bot))
